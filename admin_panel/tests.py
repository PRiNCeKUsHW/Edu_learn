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

from curriculum.models import Chapter, Class, CourseKind, Lesson, Resource, Subject
from quizzes.models import Choice, Question, Quiz

TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix='edulearn_test_media_')


class StaffGateTests(TestCase):
    """Smoke test: every list page in the panel is reachable for staff and
    blocked for everyone else — stands in for clicking through all of them
    by hand after the refactor."""

    LIST_URL_NAMES = [
        'ap:dashboard', 'ap:coursekind_list', 'ap:class_list', 'ap:subject_list',
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

    def test_admin_panel_is_unreachable_without_staff(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('ap:dashboard'))
        self.assertNotEqual(response.status_code, 200)


class SubjectCRUDTests(TestCase):
    """Simplest model — exercises the base Create/Update/Delete mixin path
    with no special-casing (slug autofill, nested back-urls, file cleanup)."""

    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(self.staff)
        self.klass = Class.objects.create(name='Class 6', slug='class-6')

    def test_add_form_shows_create_not_edit_copy(self):
        response = self.client.get(reverse('ap:subject_add'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create')
        self.assertNotContains(response, 'Save Changes')

    def test_create_edit_delete_round_trip(self):
        response = self.client.post(reverse('ap:subject_add'), {
            'klass': self.klass.pk, 'name': 'Mathematics', 'slug': 'mathematics',
            'order': 0, 'description': '', 'icon_class': 'bi-calculator',
        })
        self.assertRedirects(response, reverse('ap:subject_list'))
        subject = Subject.objects.get(slug='mathematics')

        edit_url = reverse('ap:subject_edit', args=[subject.pk])
        edit_get = self.client.get(edit_url)
        self.assertEqual(edit_get.status_code, 200)
        self.assertContains(edit_get, 'Save Changes')

        response = self.client.post(edit_url, {
            'klass': self.klass.pk, 'name': 'Maths', 'slug': 'mathematics',
            'order': 0, 'description': 'Updated', 'icon_class': 'bi-calculator',
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
    required=False and fills it in from the title, in Meta.clean(), when
    left blank — on *both* create and edit.

    Doing this in clean() rather than in the view's form_valid() (the
    original implementation) is itself the fix for a real bug: ModelForm
    validates unique_together in _post_clean(), immediately after clean()
    returns. Generating the slug afterward, in the view, meant a collision
    between two auto-generated slugs skipped that check entirely and hit
    the database as a raw IntegrityError (an unhandled 500) instead of the
    normal "already exists" form error every other duplicate hits.
    """

    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(self.staff)
        self.subject = Subject.objects.create(
            klass=Class.objects.create(name='Class 6', slug='class-6'),
            name='Mathematics', slug='mathematics',
        )

    def test_blank_slug_on_create_is_auto_generated_from_title(self):
        response = self.client.post(reverse('ap:chapter_add'), {
            'subject': self.subject.pk, 'title': 'Whole Numbers',
            'slug': '', 'order': 1, 'description': '',
        })
        self.assertRedirects(response, reverse('ap:chapter_list'))
        chapter = Chapter.objects.get(title='Whole Numbers')
        self.assertEqual(chapter.slug, 'whole-numbers')

    def test_blank_slug_on_edit_is_also_auto_generated(self):
        chapter = Chapter.objects.create(
            subject=self.subject, title='Fractions', slug='fractions', order=1,
        )
        response = self.client.post(reverse('ap:chapter_edit', args=[chapter.pk]), {
            'subject': self.subject.pk, 'title': 'Fractions and Decimals',
            'slug': '', 'order': 1, 'description': '',
        })
        self.assertRedirects(response, reverse('ap:chapter_list'))
        chapter.refresh_from_db()
        self.assertEqual(chapter.slug, 'fractions-and-decimals')

    def test_explicit_slug_is_kept_as_is(self):
        response = self.client.post(reverse('ap:chapter_add'), {
            'subject': self.subject.pk, 'title': 'Whole Numbers',
            'slug': 'wn', 'order': 1, 'description': '',
        })
        self.assertRedirects(response, reverse('ap:chapter_list'))
        self.assertEqual(Chapter.objects.get(title='Whole Numbers').slug, 'wn')

    def test_colliding_auto_generated_slug_on_create_is_a_form_error_not_a_crash(self):
        Chapter.objects.create(
            subject=self.subject, title='Introduction', slug='introduction', order=1,
        )
        response = self.client.post(reverse('ap:chapter_add'), {
            'subject': self.subject.pk, 'title': 'Introduction',
            'slug': '', 'order': 2, 'description': '',
        })
        self.assertEqual(response.status_code, 200)  # re-rendered form, not a 500
        self.assertFalse(response.context['form'].is_valid())
        self.assertIn('already exists', str(response.context['form'].errors))
        self.assertEqual(Chapter.objects.filter(subject=self.subject).count(), 1)

    def test_colliding_auto_generated_slug_on_edit_is_a_form_error_not_a_crash(self):
        Chapter.objects.create(
            subject=self.subject, title='Fractions', slug='fractions', order=1,
        )
        victim = Chapter.objects.create(
            subject=self.subject, title='Something Else', slug='something-else', order=2,
        )
        response = self.client.post(reverse('ap:chapter_edit', args=[victim.pk]), {
            'subject': self.subject.pk, 'title': 'Fractions',
            'slug': '', 'order': 2, 'description': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())
        self.assertIn('already exists', str(response.context['form'].errors))
        victim.refresh_from_db()
        self.assertEqual(victim.slug, 'something-else')  # untouched


class QuestionChoiceBackURLTests(TestCase):
    """Question/Choice cancel-and-redirect targets are nested under a quiz
    or a question, not a flat back_url_name — this is what exercises the
    back_pk positional-reversal fix (ap:choice_add's URL kwarg is named
    question_pk, not pk)."""

    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(self.staff)
        subject = Subject.objects.create(
            klass=Class.objects.create(name='Class 6', slug='class-6'),
            name='Mathematics', slug='mathematics',
        )
        chapter = Chapter.objects.create(subject=subject, title='Intro', slug='intro', order=1)
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
        subject = Subject.objects.create(
            klass=Class.objects.create(name='Class 6', slug='class-6'),
            name='Mathematics', slug='mathematics',
        )
        chapter = Chapter.objects.create(subject=subject, title='Intro', slug='intro', order=1)
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


class CourseKindCRUDTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(self.staff)

    def test_create_edit_delete_round_trip(self):
        response = self.client.post(reverse('ap:coursekind_add'), {
            'name': 'Coaching', 'slug': '', 'icon': 'bi-rocket-takeoff',
            'color': '#ef4444', 'order': 1, 'is_active': 'on', 'description': '',
        })
        self.assertRedirects(response, reverse('ap:coursekind_list'))
        kind = CourseKind.objects.get(name='Coaching')
        # Blank slug falls back to the name (SlugFromNameMixin.clean).
        self.assertEqual(kind.slug, 'coaching')

        response = self.client.post(reverse('ap:coursekind_edit', args=[kind.pk]), {
            'name': 'Coaching Batch', 'slug': 'coaching', 'icon': 'bi-rocket-takeoff',
            'color': '#ef4444', 'order': 1, 'is_active': 'on', 'description': 'Updated',
        })
        self.assertRedirects(response, reverse('ap:coursekind_list'))
        kind.refresh_from_db()
        self.assertEqual(kind.name, 'Coaching Batch')

        response = self.client.post(reverse('ap:coursekind_delete', args=[kind.pk]))
        self.assertRedirects(response, reverse('ap:coursekind_list'))
        self.assertFalse(CourseKind.objects.filter(pk=kind.pk).exists())

    def test_an_invalid_colour_is_a_form_error(self):
        response = self.client.post(reverse('ap:coursekind_add'), {
            'name': 'Workshop', 'slug': '', 'icon': 'bi-tools',
            'color': 'red', 'order': 0, 'is_active': 'on', 'description': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())
        self.assertIn('color', response.context['form'].errors)


class ClassCRUDTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(self.staff)
        self.kind = CourseKind.objects.create(name='School', slug='school')

    def _payload(self, **overrides):
        payload = {
            'name': 'Class 2', 'slug': '', 'kind': self.kind.pk,
            'icon': 'bi-mortarboard', 'order': 0, 'is_active': 'on', 'description': '',
        }
        payload.update(overrides)
        return payload

    def test_create_edit_delete_round_trip(self):
        response = self.client.post(reverse('ap:class_add'), self._payload())
        self.assertRedirects(response, reverse('ap:class_list'))
        klass = Class.objects.get(name='Class 2')
        self.assertEqual(klass.slug, 'class-2')
        self.assertEqual(klass.kind, self.kind)

        response = self.client.post(
            reverse('ap:class_edit', args=[klass.pk]),
            self._payload(name='Class Two', slug='class-2'),
        )
        self.assertRedirects(response, reverse('ap:class_list'))
        klass.refresh_from_db()
        self.assertEqual(klass.name, 'Class Two')

        response = self.client.post(reverse('ap:class_delete', args=[klass.pk]))
        self.assertRedirects(response, reverse('ap:class_list'))
        self.assertFalse(Class.objects.filter(pk=klass.pk).exists())

    def test_kind_is_optional(self):
        response = self.client.post(reverse('ap:class_add'), self._payload(
            name='UPSC Batch', kind='',
        ))
        self.assertRedirects(response, reverse('ap:class_list'))
        self.assertIsNone(Class.objects.get(name='UPSC Batch').kind)

    def test_any_name_is_accepted(self):
        for name in ('Nursery', 'IIT JEE 2027', 'Java Backend', 'Kathak Level 1'):
            with self.subTest(name=name):
                response = self.client.post(reverse('ap:class_add'), self._payload(name=name))
                self.assertRedirects(response, reverse('ap:class_list'))
                self.assertTrue(Class.objects.filter(name=name).exists())

    def test_duplicate_slug_is_a_form_error_not_a_crash(self):
        self.client.post(reverse('ap:class_add'), self._payload())
        response = self.client.post(reverse('ap:class_add'), self._payload())
        self.assertEqual(response.status_code, 200)  # re-rendered form, not a 500
        self.assertFalse(response.context['form'].is_valid())
        self.assertEqual(Class.objects.filter(slug='class-2').count(), 1)

    def test_deleting_a_class_takes_its_subjects_with_it(self):
        response = self.client.post(reverse('ap:class_add'), self._payload())
        klass = Class.objects.get(slug='class-2')
        Subject.objects.create(klass=klass, name='Maths', slug='maths')

        self.client.post(reverse('ap:class_delete', args=[klass.pk]))
        self.assertFalse(Subject.objects.filter(slug='maths').exists())


class QuizCRUDTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(self.staff)
        subject = Subject.objects.create(
            klass=Class.objects.create(name='Class 6', slug='class-6'),
            name='Mathematics', slug='mathematics',
        )
        self.chapter = Chapter.objects.create(
            subject=subject, title='Intro', slug='intro', order=1,
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
        subject = Subject.objects.create(
            klass=Class.objects.create(name='Class 6', slug='class-6'),
            name='Mathematics', slug='mathematics',
        )
        self.chapter = Chapter.objects.create(
            subject=subject, title='Intro', slug='intro', order=1,
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


class LessonSlugCollisionTests(TestCase):
    """Same bug, same fix, as ChapterSlugAutofillTests' collision tests —
    Lesson.slug is also required=False with a clean()-time auto-fill
    (unique_together is ('chapter', 'slug') here instead of
    ('subject', 'slug'))."""

    def setUp(self):
        self.staff = User.objects.create_user(username='staff', password='pass12345', is_staff=True)
        self.client.force_login(self.staff)
        subject = Subject.objects.create(
            klass=Class.objects.create(name='Class 6', slug='class-6'),
            name='Mathematics', slug='mathematics',
        )
        self.chapter = Chapter.objects.create(
            subject=subject, title='Intro', slug='intro', order=1,
        )

    def test_colliding_auto_generated_slug_on_create_is_a_form_error_not_a_crash(self):
        Lesson.objects.create(
            chapter=self.chapter, title='Overview', slug='overview',
            order=1, youtube_video_id='dQw4w9WgXcQ',
        )
        response = self.client.post(reverse('ap:lesson_add'), {
            'chapter': self.chapter.pk, 'title': 'Overview', 'slug': '',
            'order': 2, 'youtube_video_id': 'dQw4w9WgXcR',
            'description': '', 'duration_minutes': 5,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())
        self.assertIn('already exists', str(response.context['form'].errors))
        self.assertEqual(Lesson.objects.filter(chapter=self.chapter).count(), 1)

    def test_colliding_auto_generated_slug_on_edit_is_a_form_error_not_a_crash(self):
        Lesson.objects.create(
            chapter=self.chapter, title='Overview', slug='overview',
            order=1, youtube_video_id='dQw4w9WgXcQ',
        )
        victim = Lesson.objects.create(
            chapter=self.chapter, title='Something Else', slug='something-else',
            order=2, youtube_video_id='dQw4w9WgXcR',
        )
        response = self.client.post(reverse('ap:lesson_edit', args=[victim.pk]), {
            'chapter': self.chapter.pk, 'title': 'Overview', 'slug': '',
            'order': 2, 'youtube_video_id': 'dQw4w9WgXcR',
            'description': '', 'duration_minutes': 5,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())
        self.assertIn('already exists', str(response.context['form'].errors))
        victim.refresh_from_db()
        self.assertEqual(victim.slug, 'something-else')


class WriteActionPermissionTests(TestCase):
    """StaffGateTests only covers list (read) pages — this covers the
    write side: non-staff and anonymous users must be turned away from
    every add/edit/delete endpoint, not just the list views."""

    def setUp(self):
        self.subject = Subject.objects.create(
            klass=Class.objects.create(name='Class 6', slug='class-6'),
            name='Mathematics', slug='mathematics',
        )
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
