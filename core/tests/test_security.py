"""Security-boundary tests that don't fit neatly under auth/quiz/comments:
the open-redirect fix, and confirming protected actions never leak or
mutate another user's data.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Chapter, ClassLevel, Lesson, LessonProgress, Subject


class LoginRedirectSecurityTests(TestCase):
    """`next` is attacker-controlled query-string input and must never send
    a user off-site after a successful login."""

    def setUp(self):
        self.user = User.objects.create_user(username='student', password='pass12345')

    def test_external_next_url_is_ignored(self):
        url = reverse('login') + '?next=https://evil.example/phish'
        response = self.client.post(url, {'username': 'student', 'password': 'pass12345'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard'))

    def test_protocol_relative_next_url_is_ignored(self):
        """`//evil.example/` has no scheme, but browsers treat it as
        off-host — a common bypass for naive `startswith('http')` checks."""
        url = reverse('login') + '?next=//evil.example/'
        response = self.client.post(url, {'username': 'student', 'password': 'pass12345'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard'))

    def test_same_host_next_url_is_honoured(self):
        target = reverse('dashboard')
        url = reverse('login') + f'?next={target}'
        response = self.client.post(url, {'username': 'student', 'password': 'pass12345'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, target)


class UnauthorizedAccessTests(TestCase):
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

    def test_admin_panel_is_unreachable_without_staff(self):
        student = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(student)
        response = self.client.get(reverse('ap:dashboard'))
        self.assertNotEqual(response.status_code, 200)

    def test_mark_watched_requires_post(self):
        student = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(student)
        response = self.client.get(reverse('mark_watched', args=[self.lesson.pk]))
        self.assertEqual(response.status_code, 405)

    def test_mark_watched_only_affects_the_requesting_users_own_progress(self):
        alice = User.objects.create_user(username='alice', password='pass12345')
        bob = User.objects.create_user(username='bob', password='pass12345')
        LessonProgress.objects.create(user=bob, lesson=self.lesson, watched=True)

        self.client.force_login(alice)
        self.client.post(reverse('mark_watched', args=[self.lesson.pk]))

        alice_progress = LessonProgress.objects.get(user=alice, lesson=self.lesson)
        bob_progress = LessonProgress.objects.get(user=bob, lesson=self.lesson)
        self.assertTrue(alice_progress.watched)
        self.assertTrue(bob_progress.watched)  # untouched by alice's request
