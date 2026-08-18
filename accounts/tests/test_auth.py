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

from curriculum.tests.factories import make_content


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

        with self.assertLogs('accounts.views', level='WARNING') as logs:
            limited = self.client.post(reverse('login'), {
                'username': 'student', 'password': 'wrong-password',
            })
        self.assertEqual(limited.status_code, 429)
        self.assertContains(limited, 'Too many login attempts', status_code=429)
        self.assertTrue(any('Login rate limit hit' in message for message in logs.output))


class RegistrationTests(TestCase):
    """New accounts are created through Google only (see
    test_google_oauth.py::GoogleCompleteProfileViewTests for that path) --
    /register/ itself just shows the "Continue with Google" entry point and
    accepts no form data of its own, by design."""

    def setUp(self):
        cache.clear()

    def test_register_page_has_no_signup_form(self):
        response = self.client.get(reverse('register'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<form')

    def test_posting_account_details_directly_does_not_create_a_user(self):
        response = self.client.post(reverse('register'), {
            'first_name': 'New', 'last_name': 'Student',
            'username': 'newstudent', 'email': 'new@example.com',
            'password1': 'a-strong-passw0rd', 'password2': 'a-strong-passw0rd',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='newstudent').exists())

    def test_already_authenticated_user_is_redirected_away_from_register(self):
        user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(user)
        response = self.client.get(reverse('register'))
        self.assertRedirects(response, reverse('dashboard'))


class LogoutTests(TestCase):
    def test_logout_clears_the_session(self):
        user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(user)
        response = self.client.post(reverse('logout'))
        self.assertRedirects(response, reverse('landing'))
        dash = self.client.get(reverse('dashboard'))
        self.assertEqual(dash.status_code, 302)
        self.assertIn(reverse('login'), dash.url)

    def test_logout_rejects_get(self):
        """A GET logout could be fired by a prefetch or an <img> tag on any
        page, signing the student out without them clicking anything."""
        user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        # still signed in
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)


class LoginRequiredPermissionTests(TestCase):
    """Every authenticated-only view must redirect an anonymous visitor to
    login (never render the page, never 500)."""

    def setUp(self):
        _, _, _, self.lesson = make_content()
        self.protected_urls = [
            reverse('dashboard'),
            reverse('subject_list', args=['class-6']),
            reverse('chapter_list', args=['class-6', 'maths']),
            reverse('lesson_detail', args=['class-6', 'maths', 'intro', 'lesson-1']),
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
