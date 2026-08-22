"""Per-course enrollment: a student joins one course at a time, and the
dashboard shows only what they joined.

Before this existed every active class was rendered for every logged-in
student, so the dashboard read as "enrolled in everything". The tests that
matter most here are the negative ones -- that enrolling in one course does
not quietly enroll the student in the rest.
"""
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from curriculum.tests.factories import make_class, make_chapter, make_lesson, make_subject
from progress.models import Enrollment


def _course(name, slug_lessons=1):
    """A class with one subject/chapter and `slug_lessons` lessons, so it has
    enough depth to show up in the dashboard's per-class aggregation."""
    klass = make_class(name)
    chapter = make_chapter(make_subject(klass, f'{name} Subject'), 'Intro')
    for i in range(slug_lessons):
        make_lesson(chapter, title=f'Lesson {i + 1}', slug=f'lesson-{i + 1}', order=i + 1)
    return klass


class EnrollTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(self.user)
        self.maths = _course('Class 10')
        self.science = _course('Class 9')
        self.history = _course('Class 8')

    def test_enrolling_in_one_course_enrolls_in_that_course_only(self):
        """The core requirement: no fan-out to the rest of the catalogue."""
        response = self.client.post(reverse('enroll', args=[self.maths.slug]))
        self.assertRedirects(response, reverse('dashboard'))

        enrollments = Enrollment.objects.filter(user=self.user)
        self.assertEqual(enrollments.count(), 1)
        self.assertEqual(enrollments.get().klass, self.maths)
        for other in (self.science, self.history):
            self.assertFalse(
                Enrollment.objects.filter(user=self.user, klass=other).exists()
            )

    def test_enrolling_twice_is_a_no_op(self):
        self.client.post(reverse('enroll', args=[self.maths.slug]))
        response = self.client.post(reverse('enroll', args=[self.maths.slug]))
        self.assertRedirects(response, reverse('dashboard'))
        self.assertEqual(Enrollment.objects.filter(user=self.user).count(), 1)

    def test_enrolling_in_a_second_course_keeps_the_first(self):
        self.client.post(reverse('enroll', args=[self.maths.slug]))
        self.client.post(reverse('enroll', args=[self.science.slug]))
        self.assertEqual(
            set(Enrollment.objects.filter(user=self.user).values_list('klass__slug', flat=True)),
            {self.maths.slug, self.science.slug},
        )

    def test_enroll_requires_post(self):
        """A GET enroll could be fired by a prefetch or an <img> tag."""
        response = self.client.get(reverse('enroll', args=[self.maths.slug]))
        self.assertEqual(response.status_code, 405)
        self.assertFalse(Enrollment.objects.filter(user=self.user).exists())

    def test_enroll_requires_login(self):
        self.client.logout()
        response = self.client.post(reverse('enroll', args=[self.maths.slug]))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)
        self.assertFalse(Enrollment.objects.exists())

    def test_cannot_enroll_in_an_inactive_course(self):
        hidden = _course('Class 7')
        hidden.is_active = False
        hidden.save()
        response = self.client.post(reverse('enroll', args=[hidden.slug]))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Enrollment.objects.filter(klass=hidden).exists())

    def test_unknown_course_slug_404s(self):
        response = self.client.post(reverse('enroll', args=['no-such-course']))
        self.assertEqual(response.status_code, 404)


class EnrollmentIsolationTests(TestCase):
    """One student's enrollment must never become another's."""

    def setUp(self):
        self.klass = _course('Class 10')
        self.alice = User.objects.create_user(username='alice', password='pass12345')
        self.bob = User.objects.create_user(username='bob', password='pass12345')

    def test_enrolling_as_one_user_does_not_enroll_another(self):
        self.client.force_login(self.alice)
        self.client.post(reverse('enroll', args=[self.klass.slug]))
        self.assertTrue(Enrollment.objects.filter(user=self.alice).exists())
        self.assertFalse(Enrollment.objects.filter(user=self.bob).exists())

    def test_duplicate_enrollment_is_rejected_by_the_database(self):
        """The view uses get_or_create, but the constraint is what actually
        guarantees it -- a second code path can't create a duplicate."""
        Enrollment.objects.create(user=self.alice, klass=self.klass)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Enrollment.objects.create(user=self.alice, klass=self.klass)


class DashboardEnrollmentFilteringTests(TestCase):
    """The dashboard shows enrolled courses; everything else is on offer."""

    def setUp(self):
        self.user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(self.user)
        self.enrolled = _course('Class 10')
        self.other = _course('Class 9')

    def _dashboard(self):
        return self.client.get(reverse('dashboard'))

    def test_a_new_student_has_no_courses_and_sees_all_as_available(self):
        response = self._dashboard()
        self.assertEqual(response.context['class_data'], [])
        self.assertEqual(
            set(k.slug for k in response.context['available_classes']),
            {self.enrolled.slug, self.other.slug},
        )

    def test_enrolling_moves_exactly_one_course_across(self):
        self.client.post(reverse('enroll', args=[self.enrolled.slug]))
        response = self._dashboard()

        shown = [row['klass'].slug for row in response.context['class_data']]
        self.assertEqual(shown, [self.enrolled.slug])
        self.assertEqual(
            [k.slug for k in response.context['available_classes']], [self.other.slug]
        )

    def test_dashboard_totals_cover_only_enrolled_courses(self):
        """Each course has 1 lesson; enrolled in one, the denominator is 1."""
        self.client.post(reverse('enroll', args=[self.enrolled.slug]))
        response = self._dashboard()
        self.assertEqual(response.context['total_all'], 1)

    def test_my_progress_also_shows_only_enrolled_courses(self):
        self.client.post(reverse('enroll', args=[self.enrolled.slug]))
        response = self.client.get(reverse('my_progress'))
        self.assertEqual(
            [row['klass'].slug for row in response.context['class_progress']],
            [self.enrolled.slug],
        )

    def test_another_users_enrollment_does_not_appear_on_my_dashboard(self):
        bob = User.objects.create_user(username='bob', password='pass12345')
        Enrollment.objects.create(user=bob, klass=self.enrolled)
        response = self._dashboard()
        self.assertEqual(response.context['class_data'], [])
