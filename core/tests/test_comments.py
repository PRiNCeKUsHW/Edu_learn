"""Lesson comments: posting, threaded replies, and the scoping that stops a
reply from being IDOR'd onto a comment on a different lesson or nested more
than one level deep.
"""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from freezegun import freeze_time

from core.models import Comment, Lesson
from core.tests.factories import make_content


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

        with self.assertLogs('core.views', level='WARNING') as logs:
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
