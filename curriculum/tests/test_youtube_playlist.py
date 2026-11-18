"""Lessons open on youtube.com — inside the chapter's playlist when it has one —
instead of playing in an embedded player on the lesson page."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from curriculum.tests.factories import make_chapter, make_class, make_lesson, make_subject

PLAYLIST = 'PLabcdefghij1234567890'


class YouTubeWatchUrlTests(TestCase):
    def test_url_includes_chapter_playlist_when_set(self):
        lesson = make_lesson(make_chapter(youtube_playlist_id=PLAYLIST), youtube_video_id='abc123XYZ_-')
        self.assertEqual(
            lesson.youtube_watch_url,
            f'https://www.youtube.com/watch?v=abc123XYZ_-&list={PLAYLIST}',
        )

    def test_url_is_plain_watch_link_without_a_playlist(self):
        lesson = make_lesson(youtube_video_id='abc123XYZ_-')
        self.assertEqual(lesson.youtube_watch_url, 'https://www.youtube.com/watch?v=abc123XYZ_-')


class LessonPageLinksToYouTubeTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_user('learner', password='x'))
        klass = make_class('Class 9')
        subject = make_subject(klass, 'Maths')
        self.chapter = make_chapter(subject, 'Quadrilaterals', youtube_playlist_id=PLAYLIST)
        self.lesson = make_lesson(self.chapter, 'Midpoint theorem', youtube_video_id='abc123XYZ_-')
        self.url = reverse('lesson_detail', args=['class-9', 'maths', 'quadrilaterals', 'midpoint-theorem'])

    def test_player_is_a_link_to_youtube_in_a_new_tab_not_an_embed(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, '<iframe')
        self.assertContains(
            response,
            f'href="https://www.youtube.com/watch?v=abc123XYZ_-&amp;list={PLAYLIST}" target="_blank" rel="noopener"',
        )
