"""progress.0003_backfill_enrollments: students who were already studying a
class before enrollment existed must come out enrolled in it."""
from importlib import import_module

from django.apps import apps
from django.test import TestCase
from django.utils import timezone

from curriculum.tests.factories import (
    make_chapter, make_class, make_lesson, make_quiz, make_student, make_subject,
)
from progress.models import Enrollment, LessonProgress
from quizzes.models import QuizAttempt

backfill = import_module('progress.migrations.0003_backfill_enrollments').enrol_existing_students


class EnrollmentBackfillTests(TestCase):
    def setUp(self):
        self.student = make_student()
        self.watched_class = make_class('Class 9')
        self.quiz_class = make_class('Class 10')
        self.untouched_class = make_class('Class 11')

        lesson = make_lesson(make_chapter(make_subject(self.watched_class)))
        LessonProgress.objects.create(user=self.student, lesson=lesson, watched=True, watched_at=timezone.now())

        quiz = make_quiz(make_chapter(make_subject(self.quiz_class)))
        QuizAttempt.objects.create(user=self.student, quiz=quiz, score=1, total=1, passed=True)

    def enrolled(self, user):
        return set(Enrollment.objects.filter(user=user).values_list('klass__name', flat=True))

    def test_enrols_in_classes_with_progress_or_quiz_attempts(self):
        backfill(apps, None)
        self.assertEqual(self.enrolled(self.student), {'Class 9', 'Class 10'})

    def test_does_not_enrol_in_untouched_classes(self):
        backfill(apps, None)
        self.assertNotIn('Class 11', self.enrolled(self.student))

    def test_a_student_with_no_history_stays_unenrolled(self):
        newcomer = make_student('newcomer')
        backfill(apps, None)
        self.assertEqual(self.enrolled(newcomer), set())

    def test_running_twice_creates_no_duplicates(self):
        Enrollment.objects.create(user=self.student, klass=self.watched_class)
        backfill(apps, None)
        backfill(apps, None)
        self.assertEqual(Enrollment.objects.filter(user=self.student).count(), 2)
