"""Authentication: login, registration, logout, and the login_required gate
on every protected view.

Rate limiting (django-ratelimit) is keyed by IP and backed by Django's cache
framework (LocMemCache in dev/test — see settings.CACHES). That cache is a
process-wide singleton, not reset between test methods automatically, so
every test class that POSTs to a rate-limited view clears it in setUp to
stay isolated from whatever an earlier test in the same run already counted
against the same limit.

The rate-limit-tripping tests also freeze time: django-ratelimit windows by
real epoch time (ts - (ts % period), see django_ratelimit.core._get_window),
so a burst of requests that happens to straddle a window boundary can
under-count — rare, but a real flake source under --shuffle. Frozen time
removes it entirely rather than just making it less likely.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django_ratelimit.core import _split_rate
from freezegun import freeze_time

from core.models import Chapter, ClassLevel, Lesson, Subject


class LoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username='student', password='pass12345', first_name='Stu',
        )

    def test_valid_credentials_log_in_and_redirect_to_dashboard(self):
        response = self.client.post(reverse('login'), {
            'username': 'student', 'password': 'pass12345',
        })
        self.assertRedirects(response, reverse('dashboard'))
        # The session now carries an authenticated user — a follow-up
        # request to a login_required page succeeds instead of bouncing.
        dash = self.client.get(reverse('dashboard'))
        self.assertEqual(dash.status_code, 200)

    def test_invalid_credentials_show_error_without_logging_in(self):
        response = self.client.post(reverse('login'), {
            'username': 'student', 'password': 'wrong-password',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())
        # No session established — dashboard still redirects to login.
        dash = self.client.get(reverse('dashboard'))
        self.assertEqual(dash.status_code, 302)

    def test_already_authenticated_user_is_redirected_away_from_login(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('login'))
        self.assertRedirects(response, reverse('dashboard'))

    @freeze_time('2026-01-01 12:00:00')
    def test_login_rate_limited_after_configured_attempts_per_window(self):
        # Derived from settings.LOGIN_RATE_LIMIT rather than hardcoded, so
        # this test can't silently drift out of sync with the real limit —
        # see settings.py for why it's sized well above a literal 5.
        limit, _ = _split_rate(settings.LOGIN_RATE_LIMIT)
        for _ in range(limit):
            response = self.client.post(reverse('login'), {
                'username': 'student', 'password': 'wrong-password',
            })
            self.assertEqual(response.status_code, 200)

        with self.assertLogs('core.views', level='WARNING') as logs:
            limited = self.client.post(reverse('login'), {
                'username': 'student', 'password': 'wrong-password',
            })
        self.assertEqual(limited.status_code, 429)
        self.assertContains(limited, 'Too many login attempts', status_code=429)
        self.assertTrue(any('Login rate limit hit' in message for message in logs.output))


class RegistrationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_valid_registration_creates_user_and_logs_in(self):
        response = self.client.post(reverse('register'), {
            'first_name': 'New', 'last_name': 'Student',
            'username': 'newstudent', 'email': 'new@example.com',
            'password1': 'a-strong-passw0rd', 'password2': 'a-strong-passw0rd',
        })
        self.assertRedirects(response, reverse('dashboard'))
        user = User.objects.get(username='newstudent')
        self.assertEqual(user.email, 'new@example.com')
        # Registration logs the new user in immediately.
        dash = self.client.get(reverse('dashboard'))
        self.assertEqual(dash.status_code, 200)

    def test_duplicate_username_is_rejected(self):
        User.objects.create_user(username='taken', password='pass12345')
        response = self.client.post(reverse('register'), {
            'first_name': 'New', 'last_name': 'Student',
            'username': 'taken', 'email': 'new@example.com',
            'password1': 'a-strong-passw0rd', 'password2': 'a-strong-passw0rd',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())
        self.assertEqual(User.objects.filter(username='taken').count(), 1)

    def test_mismatched_passwords_are_rejected(self):
        response = self.client.post(reverse('register'), {
            'first_name': 'New', 'last_name': 'Student',
            'username': 'newstudent', 'email': 'new@example.com',
            'password1': 'a-strong-passw0rd', 'password2': 'something-else',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())
        self.assertFalse(User.objects.filter(username='newstudent').exists())

    def test_weak_password_is_rejected(self):
        response = self.client.post(reverse('register'), {
            'first_name': 'New', 'last_name': 'Student',
            'username': 'newstudent', 'email': 'new@example.com',
            'password1': '123', 'password2': '123',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())
        self.assertFalse(User.objects.filter(username='newstudent').exists())

    @freeze_time('2026-01-01 12:00:00')
    def test_registration_rate_limited_after_configured_attempts_per_window(self):
        # Derived from settings.REGISTRATION_RATE_LIMIT — see settings.py
        # for why it's sized to comfortably clear a full classroom.
        limit, _ = _split_rate(settings.REGISTRATION_RATE_LIMIT)
        for i in range(limit):
            self.client.post(reverse('register'), {
                'first_name': 'New', 'last_name': 'Student',
                'username': f'ratecheck{i}', 'email': f'rc{i}@example.com',
                'password1': 'x', 'password2': 'x',  # deliberately invalid, doesn't matter here
            })
        with self.assertLogs('core.views', level='WARNING') as logs:
            limited = self.client.post(reverse('register'), {
                'first_name': 'New', 'last_name': 'Student',
                'username': 'onemore', 'email': 'onemore@example.com',
                'password1': 'a-strong-passw0rd', 'password2': 'a-strong-passw0rd',
            })
        self.assertEqual(limited.status_code, 429)
        self.assertContains(limited, 'Too many signup attempts', status_code=429)
        self.assertFalse(User.objects.filter(username='onemore').exists())
        self.assertTrue(any('Registration rate limit hit' in message for message in logs.output))


class LogoutTests(TestCase):
    def test_logout_clears_the_session(self):
        user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(user)
        response = self.client.get(reverse('logout'))
        self.assertRedirects(response, reverse('landing'))
        dash = self.client.get(reverse('dashboard'))
        self.assertEqual(dash.status_code, 302)
        self.assertIn(reverse('login'), dash.url)


class LoginRequiredPermissionTests(TestCase):
    """Every authenticated-only view must redirect an anonymous visitor to
    login (never render the page, never 500)."""

    def setUp(self):
        subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        class_level = ClassLevel.objects.create(subject=subject, level=6)
        chapter = Chapter.objects.create(
            class_level=class_level, title='Intro', slug='intro', order=1,
        )
        self.lesson = Lesson.objects.create(
            chapter=chapter, title='Lesson 1', slug='lesson-1',
            order=1, youtube_video_id='dQw4w9WgXcQ',
        )
        self.protected_urls = [
            reverse('dashboard'),
            reverse('class_list', args=['mathematics']),
            reverse('chapter_list', args=['mathematics', 6]),
            reverse('lesson_detail', args=['mathematics', 6, 'intro', 'lesson-1']),
        ]

    def test_anonymous_get_redirects_to_login_with_next(self):
        for url in self.protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('login'), response.url)
                self.assertIn(f'next={url}', response.url)

    def test_anonymous_mark_watched_post_redirects_to_login(self):
        response = self.client.post(reverse('mark_watched', args=[self.lesson.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)
