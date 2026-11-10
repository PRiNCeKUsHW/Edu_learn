"""Lesson comments: posting, threaded replies, and the scoping that stops a
reply from being IDOR'd onto a comment on a different lesson or nested more
than one level deep.
"""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from freezegun import freeze_time

from discussions.forms import COMMENT_MAX_LENGTH
from discussions.models import Comment
from curriculum.models import Lesson
from curriculum.tests.factories import make_content
from curriculum.views import COMMENTS_PER_PAGE


class CommentPostingTests(TestCase):
    def setUp(self):
        cache.clear()  # comment posting is rate-limited; stay isolated between tests
        self.user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(self.user)

        _, _, _, self.lesson = make_content()
        self.url = reverse('lesson_detail', args=['class-6', 'maths', 'intro', 'lesson-1'])

    def test_posting_a_top_level_comment(self):
        response = self.client.post(self.url, {'comment_body': 'What is a prime number?'})
        self.assertRedirects(response, self.url)
        comment = Comment.objects.get()
        self.assertEqual(comment.user, self.user)
        self.assertEqual(comment.lesson, self.lesson)
        self.assertIsNone(comment.parent)

    def test_empty_comment_body_is_rejected(self):
        self.client.post(self.url, {'comment_body': ''})
        self.assertFalse(Comment.objects.exists())

    def test_anonymous_user_cannot_post_a_comment(self):
        self.client.logout()
        response = self.client.post(self.url, {'comment_body': 'Anonymous doubt'})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)
        self.assertFalse(Comment.objects.exists())

    def test_replying_to_a_top_level_comment(self):
        parent = Comment.objects.create(lesson=self.lesson, user=self.user, body='Original')
        response = self.client.post(self.url, {
            'comment_body': 'A reply', 'parent_id': parent.id,
        })
        self.assertRedirects(response, self.url)
        reply = Comment.objects.get(parent=parent)
        self.assertEqual(reply.body, 'A reply')
        self.assertTrue(reply.is_reply)

    def test_reply_cannot_target_a_comment_on_a_different_lesson(self):
        other_lesson = Lesson.objects.create(
            chapter=self.lesson.chapter, title='Lesson 2', slug='lesson-2',
            order=2, youtube_video_id='dQw4w9WgXcR',
        )
        foreign_comment = Comment.objects.create(
            lesson=other_lesson, user=self.user, body='On a different lesson',
        )
        response = self.client.post(self.url, {
            'comment_body': 'Trying to attach here', 'parent_id': foreign_comment.id,
        })
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Comment.objects.filter(parent=foreign_comment).exists())

    def test_reply_cannot_be_nested_under_another_reply(self):
        top = Comment.objects.create(lesson=self.lesson, user=self.user, body='Top level')
        reply = Comment.objects.create(lesson=self.lesson, user=self.user, body='A reply', parent=top)
        response = self.client.post(self.url, {
            'comment_body': 'Trying to go two levels deep', 'parent_id': reply.id,
        })
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Comment.objects.filter(parent=reply).exists())

    @freeze_time('2026-01-01 12:00:00')
    def test_rate_limited_after_ten_comments_per_minute(self):
        for i in range(10):
            response = self.client.post(self.url, {'comment_body': f'Comment {i}'})
            self.assertEqual(response.status_code, 302)
        self.assertEqual(Comment.objects.count(), 10)

        with self.assertLogs('curriculum.views', level='WARNING') as logs:
            limited_response = self.client.post(self.url, {'comment_body': 'One too many'})
        # Deliberately not assertRedirects: it does its own internal GET of
        # the target to confirm the status code, which would consume the
        # one-time flash message before the explicit follow-up GET below
        # ever sees it. Check status/target manually instead, then follow
        # exactly once ourselves.
        self.assertEqual(limited_response.status_code, 302)
        self.assertEqual(limited_response.url, self.url)
        self.assertEqual(Comment.objects.count(), 10)  # not created
        self.assertTrue(any('Comment rate limit hit' in message for message in logs.output))

        followed = self.client.get(self.url)
        self.assertContains(followed, 'posting comments too quickly')


class CommentLimitsAndPagingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(self.user)
        _, _, _, self.lesson = make_content()
        self.url = reverse('lesson_detail', args=['class-6', 'maths', 'intro', 'lesson-1'])

    def test_comment_at_the_length_limit_is_accepted(self):
        self.client.post(self.url, {'comment_body': 'x' * COMMENT_MAX_LENGTH})
        self.assertEqual(Comment.objects.count(), 1)

    def test_overlong_comment_is_rejected_with_a_message(self):
        response = self.client.post(self.url, {'comment_body': 'x' * (COMMENT_MAX_LENGTH + 1)})
        self.assertFalse(Comment.objects.exists())
        self.assertContains(response, f'at most {COMMENT_MAX_LENGTH} characters')

    def test_threads_are_paged_newest_first(self):
        for i in range(COMMENTS_PER_PAGE + 1):
            Comment.objects.create(lesson=self.lesson, user=self.user, body=f'Doubt number {i:03d}')

        first = self.client.get(self.url)
        self.assertEqual(len(first.context['comments']), COMMENTS_PER_PAGE)
        self.assertEqual(first.context['comments'].paginator.count, COMMENTS_PER_PAGE + 1)
        self.assertContains(first, f'Doubt number {COMMENTS_PER_PAGE:03d}')  # newest
        self.assertNotContains(first, 'Doubt number 000')                    # oldest
        self.assertContains(first, '?cpage=2')

        second = self.client.get(self.url, {'cpage': 2})
        self.assertContains(second, 'Doubt number 000')

    def test_reply_redirects_back_to_the_page_it_was_posted_from(self):
        parent = Comment.objects.create(lesson=self.lesson, user=self.user, body='Original')
        response = self.client.post(
            f'{self.url}?cpage=2', {'comment_body': 'A reply', 'parent_id': parent.id},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f'{self.url}?cpage=2')

    def test_query_count_does_not_grow_with_comment_authors(self):
        """Each top-level comment's author used to cost one query of its own."""
        def page_queries():
            with CaptureQueriesContext(connection) as captured:
                self.client.get(self.url)
            return len(captured)

        Comment.objects.create(lesson=self.lesson, user=self.user, body='First')
        page_queries()  # first view also creates the LessonProgress row
        baseline = page_queries()

        for i in range(5):
            author = User.objects.create_user(username=f'classmate{i}', password='pass12345')
            Comment.objects.create(lesson=self.lesson, user=author, body=f'From classmate {i}')
        self.assertEqual(page_queries(), baseline)
