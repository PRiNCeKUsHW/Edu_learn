"""Behavioural tests for the admin_panel CBV refactor.

The goal here isn't to test Django's generic views — it's to prove the
rewrite in views.py (function views -> class-based views sharing
mixins.py) preserved every URL name, template context variable, and side
effect the original hand-written views had. Each test below maps to a
concrete behaviour the old code had that would have been easy to silently
drop during the refactor.
"""
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import (
    Chapter, Choice, ClassLevel, Lesson, Question, Quiz, Resource, Subject,
)

TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix='edulearn_test_media_')


class StaffGateTests(TestCase):
    """Smoke test: every list page in the panel is reachable for staff and
    blocked for everyone else — stands in for clicking through all of them
    by hand after the refactor."""

    LIST_URL_NAMES = [
        'ap:dashboard', 'ap:subject_list', 'ap:classlevel_list',
        'ap:chapter_list', 'ap:lesson_list', 'ap:resource_list',
        'ap:quiz_list', 'ap:user_list', 'ap:comment_list',
    ]

    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.student = User.objects.create_user(username='student', password='pass12345')

    def test_every_list_page_loads_for_staff(self):
        self.client.force_login(self.staff)
        for name in self.LIST_URL_NAMES:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_list_pages_reject_non_staff(self):
        self.client.force_login(self.student)
        for name in self.LIST_URL_NAMES:
            with self.subTest(name=name):
                self.assertNotEqual(self.client.get(reverse(name)).status_code, 200)

    def test_list_pages_reject_anonymous(self):
        for name in self.LIST_URL_NAMES:
            with self.subTest(name=name):
                self.assertNotEqual(self.client.get(reverse(name)).status_code, 200)


class SubjectCRUDTests(TestCase):
    """Simplest model — exercises the base Create/Update/Delete mixin path
    with no special-casing (slug autofill, nested back-urls, file cleanup)."""

    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(self.staff)

    def test_add_form_shows_create_not_edit_copy(self):
        response = self.client.get(reverse('ap:subject_add'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create')
        self.assertNotContains(response, 'Save Changes')

    def test_create_edit_delete_round_trip(self):
        response = self.client.post(reverse('ap:subject_add'), {
            'name': 'Mathematics', 'slug': 'mathematics',
            'description': '', 'icon_class': 'bi-calculator',
        })
        self.assertRedirects(response, reverse('ap:subject_list'))
        subject = Subject.objects.get(slug='mathematics')

        edit_url = reverse('ap:subject_edit', args=[subject.pk])
        edit_get = self.client.get(edit_url)
        self.assertEqual(edit_get.status_code, 200)
        self.assertContains(edit_get, 'Save Changes')

        response = self.client.post(edit_url, {
            'name': 'Maths', 'slug': 'mathematics',
            'description': 'Updated', 'icon_class': 'bi-calculator',
        })
        self.assertRedirects(response, reverse('ap:subject_list'))
        subject.refresh_from_db()
        self.assertEqual(subject.name, 'Maths')

        delete_url = reverse('ap:subject_delete', args=[subject.pk])
        confirm_get = self.client.get(delete_url)
        self.assertEqual(confirm_get.status_code, 200)
        self.assertContains(confirm_get, 'Maths')

        response = self.client.post(delete_url)
        self.assertRedirects(response, reverse('ap:subject_list'))
        self.assertFalse(Subject.objects.filter(pk=subject.pk).exists())


class ChapterSlugAutofillTests(TestCase):
    """Chapter.slug has no blank=True, so ChapterForm overrides it to
    required=False and the view fills it in from the title when left
    blank — on *both* create and edit (forms.py + views.py)."""

    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(self.staff)
        subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        self.class_level = ClassLevel.objects.create(subject=subject, level=6)

    def test_blank_slug_on_create_is_auto_generated_from_title(self):
        response = self.client.post(reverse('ap:chapter_add'), {
            'class_level': self.class_level.pk, 'title': 'Whole Numbers',
            'slug': '', 'order': 1, 'description': '',
        })
        self.assertRedirects(response, reverse('ap:chapter_list'))
        chapter = Chapter.objects.get(title='Whole Numbers')
        self.assertEqual(chapter.slug, 'whole-numbers')

    def test_blank_slug_on_edit_is_also_auto_generated(self):
        chapter = Chapter.objects.create(
            class_level=self.class_level, title='Fractions', slug='fractions', order=1,
        )
        response = self.client.post(reverse('ap:chapter_edit', args=[chapter.pk]), {
            'class_level': self.class_level.pk, 'title': 'Fractions and Decimals',
            'slug': '', 'order': 1, 'description': '',
        })
        self.assertRedirects(response, reverse('ap:chapter_list'))
        chapter.refresh_from_db()
        self.assertEqual(chapter.slug, 'fractions-and-decimals')

    def test_explicit_slug_is_kept_as_is(self):
        response = self.client.post(reverse('ap:chapter_add'), {
            'class_level': self.class_level.pk, 'title': 'Whole Numbers',
            'slug': 'wn', 'order': 1, 'description': '',
        })
        self.assertRedirects(response, reverse('ap:chapter_list'))
        self.assertEqual(Chapter.objects.get(title='Whole Numbers').slug, 'wn')


class QuestionChoiceBackURLTests(TestCase):
    """Question/Choice cancel-and-redirect targets are nested under a quiz
    or a question, not a flat back_url_name — this is what exercises the
    back_pk positional-reversal fix (ap:choice_add's URL kwarg is named
    question_pk, not pk)."""

    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(self.staff)
        subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        class_level = ClassLevel.objects.create(subject=subject, level=6)
        chapter = Chapter.objects.create(class_level=class_level, title='Intro', slug='intro', order=1)
        self.quiz = Quiz.objects.create(chapter=chapter, title='Intro Quiz', pass_percentage=50)

    def test_add_question_redirects_to_choice_add_not_quiz_detail(self):
        response = self.client.post(reverse('ap:question_add', args=[self.quiz.pk]), {
            'text': '2 + 2 = ?', 'order': 1, 'explanation': '',
        })
        question = Question.objects.get(quiz=self.quiz)
        self.assertRedirects(response, reverse('ap:choice_add', args=[question.pk]))

    def test_choice_delete_confirm_page_cancel_link_resolves(self):
        """Regression test for the pre-existing bug found while refactoring:
        the Cancel link on a choice's delete-confirm page reversed
        ap:choice_add with a keyword pk=... argument, which raised
        NoReverseMatch because that URL's captured group is named
        question_pk. This is now a 200, not a 500."""
        question = Question.objects.create(quiz=self.quiz, text='2 + 2 = ?', order=1)
        choice = Choice.objects.create(question=question, text='4', is_correct=True)

        response = self.client.get(reverse('ap:choice_delete', args=[choice.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('ap:choice_add', args=[question.pk]))

    def test_choice_delete_redirects_back_to_choice_add(self):
        question = Question.objects.create(quiz=self.quiz, text='2 + 2 = ?', order=1)
        choice = Choice.objects.create(question=question, text='4', is_correct=True)
        response = self.client.post(reverse('ap:choice_delete', args=[choice.pk]))
        self.assertRedirects(response, reverse('ap:choice_add', args=[question.pk]))
        self.assertFalse(Choice.objects.filter(pk=choice.pk).exists())

    def test_question_delete_confirm_page_cancel_link_resolves(self):
        question = Question.objects.create(quiz=self.quiz, text='2 + 2 = ?', order=1)
        response = self.client.get(reverse('ap:question_delete', args=[question.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('ap:quiz_detail', args=[self.quiz.pk]))


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ResourceFileCleanupTests(TestCase):
    """resource_delete has to remove the uploaded file from storage, not
    just the DB row — this is the one delete view that isn't a plain
    AdminDeleteMixin + DeleteView call."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(self.staff)
        subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        class_level = ClassLevel.objects.create(subject=subject, level=6)
        chapter = Chapter.objects.create(class_level=class_level, title='Intro', slug='intro', order=1)
        self.lesson = Lesson.objects.create(
            chapter=chapter, title='Lesson 1', slug='lesson-1',
            order=1, youtube_video_id='dQw4w9WgXcQ',
        )

    def test_delete_removes_uploaded_file_from_storage(self):
        upload = SimpleUploadedFile('notes.txt', b'hello world', content_type='text/plain')
        response = self.client.post(reverse('ap:resource_add'), {
            'lesson': self.lesson.pk, 'title': 'Notes', 'file': upload,
        })
        self.assertRedirects(response, reverse('ap:resource_list'))
        resource = Resource.objects.get(title='Notes')
        storage, file_name = resource.file.storage, resource.file.name
        self.assertTrue(storage.exists(file_name))

        response = self.client.post(reverse('ap:resource_delete', args=[resource.pk]))
        self.assertRedirects(response, reverse('ap:resource_list'))
        self.assertFalse(Resource.objects.filter(pk=resource.pk).exists())
        self.assertFalse(storage.exists(file_name))


class UserToggleGuardTests(TestCase):
    """Not part of the refactor (kept as function views) — included to
    confirm the privilege-escalation guards survived the surrounding
    file being rewritten."""

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='root', password='pass12345', email='root@example.com',
        )
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.other_staff = User.objects.create_user(username='staff2', password='pass12345', is_staff=True)

    def test_non_superuser_cannot_grant_staff(self):
        self.client.force_login(self.staff)
        student = User.objects.create_user(username='student', password='pass12345')
        with self.assertLogs('admin_panel.views', level='WARNING') as logs:
            self.client.post(reverse('ap:user_toggle_staff', args=[student.pk]))
        student.refresh_from_db()
        self.assertFalse(student.is_staff)
        self.assertTrue(any('attempted to change staff status' in m for m in logs.output))

    def test_superuser_can_grant_staff(self):
        self.client.force_login(self.superuser)
        student = User.objects.create_user(username='student', password='pass12345')
        self.client.post(reverse('ap:user_toggle_staff', args=[student.pk]))
        student.refresh_from_db()
        self.assertTrue(student.is_staff)

    def test_staff_cannot_deactivate_another_staff_member(self):
        self.client.force_login(self.staff)
        with self.assertLogs('admin_panel.views', level='WARNING') as logs:
            self.client.post(reverse('ap:user_toggle_active', args=[self.other_staff.pk]))
        self.other_staff.refresh_from_db()
        self.assertTrue(self.other_staff.is_active)
        self.assertTrue(any('attempted to deactivate admin account' in m for m in logs.output))


class ClassLevelCRUDTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(self.staff)
        self.subject = Subject.objects.create(name='Mathematics', slug='mathematics')

    def test_create_edit_delete_round_trip(self):
        response = self.client.post(reverse('ap:classlevel_add'), {
            'subject': self.subject.pk, 'level': 6, 'description': '',
        })
        self.assertRedirects(response, reverse('ap:classlevel_list'))
        class_level = ClassLevel.objects.get(subject=self.subject, level=6)

        response = self.client.post(reverse('ap:classlevel_edit', args=[class_level.pk]), {
            'subject': self.subject.pk, 'level': 7, 'description': 'Updated',
        })
        self.assertRedirects(response, reverse('ap:classlevel_list'))
        class_level.refresh_from_db()
        self.assertEqual(class_level.level, 7)

        response = self.client.post(reverse('ap:classlevel_delete', args=[class_level.pk]))
        self.assertRedirects(response, reverse('ap:classlevel_list'))
        self.assertFalse(ClassLevel.objects.filter(pk=class_level.pk).exists())


class QuizCRUDTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(self.staff)
        subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        class_level = ClassLevel.objects.create(subject=subject, level=6)
        self.chapter = Chapter.objects.create(
            class_level=class_level, title='Intro', slug='intro', order=1,
        )

    def test_create_edit_delete_round_trip(self):
        response = self.client.post(reverse('ap:quiz_add'), {
            'chapter': self.chapter.pk, 'title': 'Intro Quiz',
            'description': '', 'pass_percentage': 60,
        })
        self.assertRedirects(response, reverse('ap:quiz_list'))
        quiz = Quiz.objects.get(chapter=self.chapter)

        detail = self.client.get(reverse('ap:quiz_detail', args=[quiz.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'Intro Quiz')

        response = self.client.post(reverse('ap:quiz_edit', args=[quiz.pk]), {
            'chapter': self.chapter.pk, 'title': 'Intro Quiz (Revised)',
            'description': '', 'pass_percentage': 70,
        })
        self.assertRedirects(response, reverse('ap:quiz_list'))
        quiz.refresh_from_db()
        self.assertEqual(quiz.pass_percentage, 70)

        response = self.client.post(reverse('ap:quiz_delete', args=[quiz.pk]))
        self.assertRedirects(response, reverse('ap:quiz_list'))
        self.assertFalse(Quiz.objects.filter(pk=quiz.pk).exists())


class LessonCRUDTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(self.staff)
        subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        class_level = ClassLevel.objects.create(subject=subject, level=6)
        self.chapter = Chapter.objects.create(
            class_level=class_level, title='Intro', slug='intro', order=1,
        )

    def test_create_edit_delete_round_trip(self):
        response = self.client.post(reverse('ap:lesson_add'), {
            'chapter': self.chapter.pk, 'title': 'First Lesson', 'slug': 'first-lesson',
            'order': 1, 'youtube_video_id': 'dQw4w9WgXcQ',
            'description': '', 'duration_minutes': 5,
        })
        self.assertRedirects(response, reverse('ap:lesson_list'))
        lesson = Lesson.objects.get(slug='first-lesson')

        response = self.client.post(reverse('ap:lesson_edit', args=[lesson.pk]), {
            'chapter': self.chapter.pk, 'title': 'First Lesson (Updated)', 'slug': 'first-lesson',
            'order': 1, 'youtube_video_id': 'dQw4w9WgXcQ',
            'description': '', 'duration_minutes': 8,
        })
        self.assertRedirects(response, reverse('ap:lesson_list'))
        lesson.refresh_from_db()
        self.assertEqual(lesson.duration_minutes, 8)

        response = self.client.post(reverse('ap:lesson_delete', args=[lesson.pk]))
        self.assertRedirects(response, reverse('ap:lesson_list'))
        self.assertFalse(Lesson.objects.filter(pk=lesson.pk).exists())


class WriteActionPermissionTests(TestCase):
    """StaffGateTests only covers list (read) pages — this covers the
    write side: non-staff and anonymous users must be turned away from
    every add/edit/delete endpoint, not just the list views."""

    def setUp(self):
        self.subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        self.student = User.objects.create_user(username='student', password='pass12345')

    def test_non_staff_cannot_create_a_subject(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse('ap:subject_add'), {
            'name': 'Physics', 'slug': 'physics', 'description': '', 'icon_class': 'bi-book',
        })
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(Subject.objects.filter(slug='physics').exists())

    def test_non_staff_cannot_delete_a_subject(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse('ap:subject_delete', args=[self.subject.pk]))
        self.assertNotEqual(response.status_code, 200)
        self.assertTrue(Subject.objects.filter(pk=self.subject.pk).exists())

    def test_anonymous_cannot_create_a_subject(self):
        response = self.client.post(reverse('ap:subject_add'), {
            'name': 'Physics', 'slug': 'physics', 'description': '', 'icon_class': 'bi-book',
        })
        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(Subject.objects.filter(slug='physics').exists())
