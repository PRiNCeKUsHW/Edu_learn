"""Progress tracking: the mark-watched AJAX toggle and the dashboard's
aggregate calculations (overall %, per-subject %, streak, resume target),
plus the student's own Progress report card (marks, completion, study time).
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from django.db import connection
from django.test.utils import CaptureQueriesContext

from curriculum.models import Lesson
from progress.models import Enrollment, LessonProgress
from quizzes.models import QuizAttempt
from curriculum.tests.factories import (
    make_chapter, make_class, make_content, make_lesson, make_quiz, make_subject,
)


class MarkWatchedTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(self.user)
        _, _, _, self.lesson = make_content()
        self.url = reverse('mark_watched', args=[self.lesson.pk])

    def test_toggling_on_sets_watched_with_a_timestamp(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'watched': True})
        progress = LessonProgress.objects.get(user=self.user, lesson=self.lesson)
        self.assertTrue(progress.watched)
        self.assertIsNotNone(progress.watched_at)

    def test_toggling_again_clears_watched_and_timestamp(self):
        self.client.post(self.url)
        response = self.client.post(self.url)
        self.assertEqual(response.json(), {'watched': False})
        progress = LessonProgress.objects.get(user=self.user, lesson=self.lesson)
        self.assertFalse(progress.watched)
        self.assertIsNone(progress.watched_at)

    def test_first_call_creates_the_progress_row(self):
        self.assertFalse(LessonProgress.objects.filter(user=self.user, lesson=self.lesson).exists())
        self.client.post(self.url)
        self.assertTrue(LessonProgress.objects.filter(user=self.user, lesson=self.lesson).exists())


class DashboardCalculationTests(TestCase):
    """Builds a fixture with a known, hand-computable answer for every
    number the dashboard shows, so a regression in the aggregation query
    changes a concrete expected value instead of failing silently."""

    def setUp(self):
        self.user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(self.user)

        klass = make_class('Class 6')
        maths_chapter = make_chapter(make_subject(klass, 'Maths'), 'Numbers')
        self.lessons = [
            Lesson.objects.create(
                chapter=maths_chapter, title=f'Lesson {i}', slug=f'lesson-{i}',
                order=i, youtube_video_id='dQw4w9WgXcQ',
            )
            for i in range(1, 5)  # 4 lessons total
        ]

        # A second class holding a chapter but no lessons — must not raise a
        # division-by-zero when computing its percentage.
        self.empty_class = make_class('Class 7')
        make_chapter(make_subject(self.empty_class, 'Science'), 'Empty')


        # The dashboard now renders only courses the student has joined. These
        # assertions are about the aggregation maths, so enrol in the fixture's
        # courses and leave the filtering itself to test_enrollment.py.
        for course in (klass, self.empty_class):
            Enrollment.objects.create(user=self.user, klass=course)

        # Watch 3 of the 4 maths lessons -> 75% overall (4 total lessons project-wide).
        for lesson in self.lessons[:3]:
            LessonProgress.objects.create(
                user=self.user, lesson=lesson, watched=True, watched_at=timezone.now(),
            )

    def test_overall_and_per_class_percentages(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['watched_all'], 3)
        self.assertEqual(response.context['total_all'], 4)
        self.assertEqual(response.context['overall_percent'], 75)

        by_class = {row['klass'].slug: row for row in response.context['class_data']}
        self.assertEqual(by_class['class-6']['percent'], 75)
        self.assertEqual(by_class['class-7']['percent'], 0)  # no lessons, not a crash

    def test_streak_counts_consecutive_days_ending_today(self):
        # Re-mark across three consecutive days, including today.
        LessonProgress.objects.all().delete()
        for offset, lesson in zip((2, 1, 0), self.lessons[:3]):
            LessonProgress.objects.create(
                user=self.user, lesson=lesson, watched=True,
                watched_at=timezone.now() - timedelta(days=offset),
            )
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['streak'], 3)

    def test_streak_is_zero_with_no_activity(self):
        LessonProgress.objects.all().delete()
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['streak'], 0)

    def test_week_activity_always_has_seven_entries_ending_today(self):
        response = self.client.get(reverse('dashboard'))
        week = response.context['week_activity']
        self.assertEqual(len(week), 7)
        self.assertEqual(week[-1]['day'], timezone.localdate())

    def test_resume_lesson_is_the_first_unwatched_lesson_in_last_active_chapter(self):
        response = self.client.get(reverse('dashboard'))
        # Lessons 1-3 watched, lesson 4 is not -> resume should point at it.
        self.assertEqual(response.context['resume_lesson'].slug, 'lesson-4')

    def test_resume_lesson_is_none_with_no_activity(self):
        LessonProgress.objects.all().delete()
        response = self.client.get(reverse('dashboard'))
        self.assertIsNone(response.context['resume_lesson'])


class MyProgressTests(TestCase):
    """The student-facing report card. The fixture is built so every number
    the page shows has one hand-computable answer, and so the two edge cases
    that can crash an aggregate — a class with no lessons and an attempt with
    total=0 — are present from the start rather than bolted on later."""

    def setUp(self):
        self.user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(self.user)
        self.url = reverse('my_progress')

        klass = make_class('Class 6')
        subject = make_subject(klass, 'Maths')
        chapter = make_chapter(subject, 'Numbers')
        # 4 lessons, 3 watched -> 75%. Durations sum to 30 across the watched
        # three; the unwatched one carries time that must NOT be counted.
        self.lessons = [
            make_lesson(chapter, title=f'Lesson {i}', slug=f'lesson-{i}', order=i,
                        duration_minutes=10)
            for i in range(1, 5)
        ]
        for lesson in self.lessons[:3]:
            LessonProgress.objects.create(
                user=self.user, lesson=lesson, watched=True, watched_at=timezone.now(),
            )
        # An opened-but-unwatched row: created lazily by the lesson page, and
        # must not count towards completion.
        LessonProgress.objects.create(user=self.user, lesson=self.lessons[3], watched=False)

        # A class holding a chapter but no lessons — must be dropped, not
        # rendered at 0%, and must not divide by zero.
        empty_class = make_class('Class 7')
        make_chapter(make_subject(empty_class, 'Science'), 'Intro')

        # The dashboard now renders only courses the student has joined. These
        # assertions are about the aggregation maths, so enrol in the fixture's
        # courses and leave the filtering itself to test_enrollment.py.
        for course in (klass, empty_class):
            Enrollment.objects.create(user=self.user, klass=course)

        # Marks: 5/10 (50%, failed) and 9/10 (90%, passed) on one quiz,
        # 2/4 (50%, failed) on another. Average of 50, 90, 50 = 63.33 -> 63.
        self.quiz = make_quiz(chapter, title='Numbers Quiz', questions=1)
        other = make_quiz(make_chapter(subject, 'Algebra', slug='algebra'),
                          title='Algebra Quiz', questions=1)
        QuizAttempt.objects.create(user=self.user, quiz=self.quiz, score=5, total=10, passed=False)
        QuizAttempt.objects.create(user=self.user, quiz=self.quiz, score=9, total=10, passed=True)
        QuizAttempt.objects.create(user=self.user, quiz=other, score=2, total=4, passed=False)

    def test_lesson_completion_counts_only_watched_rows(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['watched_all'], 3)
        self.assertEqual(response.context['total_all'], 4)
        self.assertEqual(response.context['overall_percent'], 75)

    def test_empty_class_is_dropped_from_the_breakdown(self):
        rows = self.client.get(self.url).context['class_progress']
        by_slug = {row['klass'].slug: row for row in rows}
        self.assertEqual(by_slug['class-6']['percent'], 75)
        self.assertNotIn('class-7', by_slug)  # no lessons, not a 0% row

    def test_quiz_counts_are_distinct_quizzes_but_attempts_are_rows(self):
        stats = self.client.get(self.url).context['stats']
        self.assertEqual(stats['attempts_count'], 3)   # retakes each count
        self.assertEqual(stats['quizzes_given'], 2)    # two distinct quizzes
        self.assertEqual(stats['quizzes_passed'], 1)   # one of them passed

    def test_average_and_best_score_percentages(self):
        stats = self.client.get(self.url).context['stats']
        self.assertEqual(stats['avg_percent'], 63)  # (50 + 90 + 50) / 3
        self.assertEqual(stats['best_percent'], 90)

    def test_study_minutes_sums_only_watched_lessons(self):
        self.assertEqual(self.client.get(self.url).context['study_minutes'], 30)

    def test_history_lists_every_attempt_newest_first(self):
        attempts = list(self.client.get(self.url).context['attempts'])
        self.assertEqual(len(attempts), 3)
        self.assertEqual(attempts[0].attempted_at, max(a.attempted_at for a in attempts))

    def test_a_zero_question_attempt_is_excluded_from_the_average(self):
        """The row still counts as an attempt but can't contribute a
        percentage. Note this asserts values only: the tests run on SQLite,
        which returns NULL for x/0, so it would pass even without the
        exclude() in quiz_stats. The exclude is there for PostgreSQL, which
        raises division_by_zero instead."""
        QuizAttempt.objects.create(user=self.user, quiz=self.quiz, score=0, total=0, passed=False)
        stats = self.client.get(self.url).context['stats']
        self.assertEqual(stats['attempts_count'], 4)
        self.assertEqual(stats['avg_percent'], 63)  # unchanged
        self.assertEqual(stats['best_percent'], 90)


class MyProgressEmptyStateTests(TestCase):
    """A brand-new student has no progress rows and no attempts at all: every
    aggregate returns None from the database and must render as 0, not crash."""

    def test_a_student_with_no_activity_sees_zeroes(self):
        user = User.objects.create_user(username='fresh', password='pass12345')
        self.client.force_login(user)
        make_content()

        response = self.client.get(reverse('my_progress'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['overall_percent'], 0)
        self.assertEqual(response.context['study_minutes'], 0)
        self.assertEqual(response.context['streak'], 0)
        self.assertEqual(list(response.context['attempts']), [])
        stats = response.context['stats']
        self.assertEqual(stats['avg_percent'], 0)
        self.assertEqual(stats['best_percent'], 0)
        self.assertEqual(stats['quizzes_given'], 0)


class MyProgressQueryCountTests(TestCase):
    """Locks the select_related on the attempt history. Each row names its
    quiz, chapter, subject and class, so without it the page issues four
    extra queries per attempt and scales with the student's history."""

    def test_query_count_does_not_grow_with_attempt_count(self):
        user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(user)
        chapter = make_chapter(make_subject(make_class(), 'Maths'), 'Numbers')
        quiz = make_quiz(chapter, title='Numbers Quiz', questions=1)
        for _ in range(12):
            QuizAttempt.objects.create(user=user, quiz=quiz, score=5, total=10, passed=False)

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(reverse('my_progress'))
        self.assertEqual(response.status_code, 200)
        # Constant regardless of the 12 attempts above: the class annotation,
        # the attempt list, the four quiz-stat aggregates, study minutes, the
        # streak day set, plus the session/auth lookups the test client makes.
        self.assertLess(len(ctx.captured_queries), 15)


class MyProgressQuizLinkTests(TestCase):
    """Every quiz row links to its own attempt. Pinning the id matters
    because the list shows retakes: without ?attempt= both rows of a retaken
    quiz would open the newest attempt's answers."""

    def setUp(self):
        self.user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(self.user)
        chapter = make_chapter(make_subject(make_class('Class 10'), 'Mathematics'), 'Real Numbers')
        self.quiz = make_quiz(chapter, title='Real Numbers Quiz', questions=1)
        self.first = QuizAttempt.objects.create(
            user=self.user, quiz=self.quiz, score=4, total=10, passed=False)
        self.retake = QuizAttempt.objects.create(
            user=self.user, quiz=self.quiz, score=8, total=10, passed=True)

    def test_each_row_links_to_its_own_attempt(self):
        html = self.client.get(reverse('my_progress')).content.decode()
        base = reverse('quiz_analysis', args=['class-10', 'mathematics', 'real-numbers'])
        self.assertIn(f'{base}?attempt={self.first.id}', html)
        self.assertIn(f'{base}?attempt={self.retake.id}', html)

    def test_the_link_resolves_to_that_attempts_analysis(self):
        """Follows the rendered link rather than trusting the URL shape."""
        base = reverse('quiz_analysis', args=['class-10', 'mathematics', 'real-numbers'])
        response = self.client.get(base, {'attempt': self.first.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['attempt'], self.first)
