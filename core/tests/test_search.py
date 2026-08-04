"""Student-facing search across subjects, chapters and lessons."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Chapter, ClassLevel, Lesson, Subject


class SearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(self.user)

        maths = Subject.objects.create(
            name='Mathematics', slug='mathematics', description='Numbers and equations',
        )
        science = Subject.objects.create(name='Science', slug='science')

        maths_cl = ClassLevel.objects.create(subject=maths, level=6)
        self.chapter = Chapter.objects.create(
            class_level=maths_cl, title='Whole Numbers', slug='whole-numbers', order=1,
        )
        self.lesson = Lesson.objects.create(
            chapter=self.chapter, title='Introduction to Whole Numbers', slug='intro',
            order=1, youtube_video_id='dQw4w9WgXcQ',
        )
        # A science chapter/lesson to prove search doesn't just return everything.
        science_cl = ClassLevel.objects.create(subject=science, level=6)
        Chapter.objects.create(class_level=science_cl, title='Living Things', slug='living-things', order=1)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('search'), {'q': 'numbers'})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_blank_query_shows_no_results_and_no_crash(self):
        response = self.client.get(reverse('search'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['subjects_page'].paginator.count, 0)
        self.assertContains(response, 'Start typing to search')

    def test_partial_case_insensitive_match_on_subject(self):
        response = self.client.get(reverse('search'), {'q': 'MATH'})
        self.assertContains(response, 'Mathematics')
        self.assertNotContains(response, 'Science')

    def test_partial_case_insensitive_match_on_chapter(self):
        response = self.client.get(reverse('search'), {'q': 'whole num'})
        self.assertContains(response, 'Whole Numbers')
        self.assertNotContains(response, 'Living Things')

    def test_partial_case_insensitive_match_on_lesson(self):
        response = self.client.get(reverse('search'), {'q': 'introduction'})
        self.assertContains(response, 'Introduction to Whole Numbers')

    def test_matches_subject_description_too(self):
        response = self.client.get(reverse('search'), {'q': 'equations'})
        self.assertContains(response, 'Mathematics')

    def test_no_results_state(self):
        response = self.client.get(reverse('search'), {'q': 'zzz-nonexistent-zzz'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No results for')

    def test_result_links_point_at_the_right_pages(self):
        response = self.client.get(reverse('search'), {'q': 'whole'})
        self.assertContains(
            response, reverse('chapter_list', args=['mathematics', 6]),
        )

    def test_sections_paginate_independently(self):
        # 12 chapters all matching "chapter n" -> 2 pages at 10/page, while
        # subjects/lessons have few enough results to stay on page 1.
        cl = ClassLevel.objects.create(
            subject=Subject.objects.first(), level=7,
        )
        for i in range(12):
            Chapter.objects.create(
                class_level=cl, title=f'Chapter Search Target {i}', slug=f'target-{i}', order=i,
            )
        response = self.client.get(reverse('search'), {'q': 'chapter search target', 'cpage': 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['chapters_page'].number, 2)
        self.assertEqual(len(response.context['chapters_page']), 2)  # 12 - 10 on page 2
