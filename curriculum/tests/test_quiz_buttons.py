"""Chapter list / lesson detail must offer a single "Take quiz" button until
the student has attempted the chapter's quiz, then switch to "Retry" +
"View analysis" instead.
"""
from django.test import TestCase
from django.urls import reverse

from quizzes.models import QuizAttempt

from .factories import make_chapter, make_class, make_lesson, make_quiz, make_student, make_subject


class ChapterListQuizButtonTests(TestCase):
    def setUp(self):
        self.user = make_student()
        self.client.force_login(self.user)
        klass = make_class('Class 6')
        subject = make_subject(klass, 'Maths')
        chapter = make_chapter(subject, 'Numbers')
        self.quiz = make_quiz(chapter, 'Numbers Quiz')
        self.url = reverse('chapter_list', args=['class-6', 'maths'])

    def test_shows_take_quiz_button_with_no_prior_attempt(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Take quiz')
        self.assertNotContains(response, 'View analysis')

    def test_shows_retry_and_view_analysis_after_an_attempt(self):
        QuizAttempt.objects.create(user=self.user, quiz=self.quiz, score=1, total=1, passed=True)
        response = self.client.get(self.url)
        self.assertContains(response, 'Retry')
        self.assertContains(response, 'View analysis')
        self.assertNotContains(response, 'Take quiz')


class LessonDetailQuizButtonTests(TestCase):
    def setUp(self):
        self.user = make_student()
        self.client.force_login(self.user)
        klass = make_class('Class 6')
        subject = make_subject(klass, 'Maths')
        chapter = make_chapter(subject, 'Numbers')
        self.lesson = make_lesson(chapter, 'Lesson 1')
        self.quiz = make_quiz(chapter, 'Numbers Quiz')
        self.url = reverse('lesson_detail', args=['class-6', 'maths', 'numbers', 'lesson-1'])

    def test_shows_take_quiz_button_with_no_prior_attempt(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'Take quiz')
        self.assertNotContains(response, 'View analysis')

    def test_shows_retry_and_view_analysis_after_an_attempt(self):
        QuizAttempt.objects.create(user=self.user, quiz=self.quiz, score=1, total=1, passed=True)
        response = self.client.get(self.url)
        self.assertContains(response, 'Retry')
        self.assertContains(response, 'View analysis')
        self.assertNotContains(response, 'Take quiz')
