"""Progress tracking: the mark-watched AJAX toggle and the dashboard's
aggregate calculations (overall %, per-subject %, streak, resume target).
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Chapter, ClassLevel, Lesson, LessonProgress, Subject


class MarkWatchedTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(self.user)
        subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        class_level = ClassLevel.objects.create(subject=subject, level=6)
        chapter = Chapter.objects.create(
            class_level=class_level, title='Intro', slug='intro', order=1,
        )
        self.lesson = Lesson.objects.create(
            chapter=chapter, title='Lesson 1', slug='lesson-1',
            order=1, youtube_video_id='dQw4w9WgXcQ',
        )
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

        maths = Subject.objects.create(name='Mathematics', slug='mathematics')
        maths_cl = ClassLevel.objects.create(subject=maths, level=6)
        maths_chapter = Chapter.objects.create(
            class_level=maths_cl, title='Numbers', slug='numbers', order=1,
        )
        self.lessons = [
            Lesson.objects.create(
                chapter=maths_chapter, title=f'Lesson {i}', slug=f'lesson-{i}',
                order=i, youtube_video_id='dQw4w9WgXcQ',
            )
            for i in range(1, 5)  # 4 lessons total
        ]

        science = Subject.objects.create(name='Science', slug='science')
        science_cl = ClassLevel.objects.create(subject=science, level=6)
        Chapter.objects.create(class_level=science_cl, title='Empty', slug='empty', order=1)
        # Science has a chapter but no lessons — must not raise a
        # division-by-zero when computing its percentage.

        # Watch 3 of the 4 maths lessons -> 75% overall (4 total lessons project-wide).
        for lesson in self.lessons[:3]:
            LessonProgress.objects.create(
                user=self.user, lesson=lesson, watched=True, watched_at=timezone.now(),
            )

    def test_overall_and_per_subject_percentages(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['watched_all'], 3)
        self.assertEqual(response.context['total_all'], 4)
        self.assertEqual(response.context['overall_percent'], 75)

        by_subject = {row['subject'].slug: row for row in response.context['subject_data']}
        self.assertEqual(by_subject['mathematics']['percent'], 75)
        self.assertEqual(by_subject['science']['percent'], 0)  # no lessons, not a crash

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
