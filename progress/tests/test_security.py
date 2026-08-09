"""Security-boundary tests: mark_watched must never leak or mutate another
user's progress, and must reject anything but POST."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from curriculum.tests.factories import make_content
from progress.models import LessonProgress


class UnauthorizedAccessTests(TestCase):
    def setUp(self):
        _, _, _, self.lesson = make_content()

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
