"""Security-boundary tests: mark_watched must never leak or mutate another
user's progress and must reject anything but POST, and the Progress report
card must only ever show the signed-in student their own marks."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from curriculum.tests.factories import make_content, make_quiz
from progress.models import LessonProgress
from quizzes.models import QuizAttempt


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


class MyProgressIsolationTests(TestCase):
    """The Progress page reports marks, so it must never show one student
    another student's numbers, and must not be reachable signed out."""

    def setUp(self):
        _, _, self.chapter, self.lesson = make_content()
        self.quiz = make_quiz(self.chapter, title='Numbers Quiz', questions=1)
        self.url = reverse('my_progress')

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_shows_only_the_requesting_users_attempts(self):
        alice = User.objects.create_user(username='alice', password='pass12345')
        bob = User.objects.create_user(username='bob', password='pass12345')
        QuizAttempt.objects.create(user=alice, quiz=self.quiz, score=3, total=10, passed=False)
        QuizAttempt.objects.create(user=bob, quiz=self.quiz, score=10, total=10, passed=True)

        self.client.force_login(alice)
        response = self.client.get(self.url)

        attempts = list(response.context['attempts'])
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].user, alice)
        stats = response.context['stats']
        self.assertEqual(stats['best_percent'], 30)   # alice's own, not bob's 100
        self.assertEqual(stats['quizzes_passed'], 0)

    def test_shows_only_the_requesting_users_lesson_progress(self):
        alice = User.objects.create_user(username='alice', password='pass12345')
        bob = User.objects.create_user(username='bob', password='pass12345')
        LessonProgress.objects.create(user=bob, lesson=self.lesson, watched=True)

        self.client.force_login(alice)
        response = self.client.get(self.url)
        self.assertEqual(response.context['watched_all'], 0)  # bob's watch isn't alice's
