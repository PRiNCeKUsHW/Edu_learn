"""The dashboard's lesson rails: "Recently watched" (driven by
LessonProgress.last_viewed_at) and "Up next" (recommended_lessons), plus the
episode position every lesson card prints.
"""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from curriculum.selectors import attach_positions, latest_lessons
from curriculum.tests.factories import (
    make_chapter, make_class, make_lesson, make_student, make_subject,
)
from progress.models import LessonProgress
from progress.selectors import recently_viewed, recommended_lessons


def lesson_url(lesson):
    chapter = lesson.chapter
    return reverse('lesson_detail', args=[
        chapter.subject.klass.slug, chapter.subject.slug, chapter.slug, lesson.slug,
    ])


class ViewTrackingTests(TestCase):
    def setUp(self):
        self.user = make_student()
        self.client.force_login(self.user)
        self.lesson = make_lesson(make_chapter(make_subject(make_class())))

    def test_opening_a_lesson_records_when_it_was_viewed(self):
        before = timezone.now()
        self.client.get(lesson_url(self.lesson))
        progress = LessonProgress.objects.get(user=self.user, lesson=self.lesson)
        self.assertIsNotNone(progress.last_viewed_at)
        self.assertGreaterEqual(progress.last_viewed_at, before)

    def test_viewing_does_not_mark_the_lesson_watched(self):
        self.client.get(lesson_url(self.lesson))
        self.assertFalse(LessonProgress.objects.get(user=self.user, lesson=self.lesson).watched)

    def test_posting_a_comment_does_not_count_as_a_view(self):
        self.client.post(lesson_url(self.lesson), {'comment_body': 'A doubt'})
        progress = LessonProgress.objects.get(user=self.user, lesson=self.lesson)
        self.assertIsNone(progress.last_viewed_at)


class RecentlyViewedTests(TestCase):
    def setUp(self):
        self.user = make_student()
        chapter = make_chapter(make_subject(make_class()))
        self.first = make_lesson(chapter, 'First', order=1)
        self.second = make_lesson(chapter, 'Second', order=2)
        now = timezone.now()
        LessonProgress.objects.create(user=self.user, lesson=self.first, last_viewed_at=now - timedelta(hours=2))
        LessonProgress.objects.create(user=self.user, lesson=self.second, last_viewed_at=now)

    def test_newest_view_comes_first(self):
        titles = [row.lesson.title for row in recently_viewed(self.user)]
        self.assertEqual(titles, ['Second', 'First'])

    def test_rows_never_viewed_are_left_out(self):
        third = make_lesson(self.first.chapter, 'Third', order=3)
        LessonProgress.objects.create(user=self.user, lesson=third, watched=True, watched_at=timezone.now())
        titles = [row.lesson.title for row in recently_viewed(self.user)]
        self.assertNotIn('Third', titles)

    def test_lessons_under_a_hidden_class_are_left_out(self):
        klass = self.first.chapter.subject.klass
        klass.is_active = False
        klass.save()
        self.assertEqual(recently_viewed(self.user), [])

    def test_another_students_views_are_not_shown(self):
        self.assertEqual(recently_viewed(make_student('other')), [])

    def test_each_row_carries_its_episode_position(self):
        rows = recently_viewed(self.user)
        self.assertEqual((rows[0].lesson.ep_index, rows[0].lesson.ep_total), (2, 2))


class RecommendedLessonsTests(TestCase):
    def setUp(self):
        self.user = make_student()
        subject = make_subject(make_class())
        self.chapter = make_chapter(subject, 'Quadrilaterals', order=12)
        self.lessons = [make_lesson(self.chapter, f'L{i}', order=i) for i in range(1, 5)]

    def test_new_student_gets_the_newest_lessons(self):
        picks = recommended_lessons(self.user, limit=3)
        self.assertEqual(len(picks), 3)

    def test_next_unwatched_lessons_in_the_chapter_in_progress(self):
        LessonProgress.objects.create(
            user=self.user, lesson=self.lessons[0], watched=True,
            watched_at=timezone.now(), last_viewed_at=timezone.now(),
        )
        picks = recommended_lessons(self.user, limit=2)
        self.assertEqual([lesson.title for lesson in picks], ['L2', 'L3'])

    def test_at_most_two_picks_come_from_one_chapter_before_falling_back(self):
        LessonProgress.objects.create(user=self.user, lesson=self.lessons[0], last_viewed_at=timezone.now())
        other = make_lesson(make_chapter(self.chapter.subject, 'Other', order=13), 'Elsewhere')
        picks = recommended_lessons(self.user, limit=3)
        self.assertEqual([lesson.title for lesson in picks][:2], ['L1', 'L2'])
        self.assertIn(other, picks)

    def test_watched_and_excluded_lessons_are_never_recommended(self):
        LessonProgress.objects.create(user=self.user, lesson=self.lessons[1], watched=True, watched_at=timezone.now())
        picks = recommended_lessons(self.user, limit=6, exclude_ids=[self.lessons[0].id])
        titles = [lesson.title for lesson in picks]
        self.assertNotIn('L1', titles)
        self.assertNotIn('L2', titles)

    def test_picks_carry_episode_positions(self):
        picks = recommended_lessons(self.user, limit=4)
        self.assertTrue(all(lesson.ep_total == 4 for lesson in picks))


class EpisodePositionTests(TestCase):
    def test_position_is_the_lessons_place_within_its_own_chapter(self):
        chapter = make_chapter(make_subject(make_class()))
        lessons = [make_lesson(chapter, f'L{i}', order=i) for i in (1, 2, 3)]
        attach_positions(lessons)
        self.assertEqual([(l.ep_index, l.ep_total) for l in lessons], [(1, 3), (2, 3), (3, 3)])

    def test_latest_lessons_skips_hidden_subjects(self):
        subject = make_subject(make_class())
        make_lesson(make_chapter(subject))
        subject.is_active = False
        subject.save()
        self.assertEqual(latest_lessons(), [])


class DashboardRailsRenderTests(TestCase):
    def setUp(self):
        self.user = make_student()
        self.client.force_login(self.user)
        self.lesson = make_lesson(make_chapter(make_subject(make_class('Class 9'), 'Mathematics'), 'Quadrilaterals', order=12), 'Varignon')

    def test_viewed_lesson_appears_under_recently_watched(self):
        self.client.get(lesson_url(self.lesson))
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'id="recentHeading"')
        self.assertEqual([row.lesson for row in response.context['recent_views']], [self.lesson])

    def test_new_student_sees_up_next_but_no_history(self):
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'id="upNextHeading"')
        self.assertNotContains(response, 'id="recentHeading"')
        self.assertEqual(response.context['recent_views'], [])
