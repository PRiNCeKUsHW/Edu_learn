"""The fully dynamic hierarchy: CourseKind → Class → Subject → Chapter → Lesson.

The point of these tests is that nothing about the education structure is baked
into the code. Every row here is one an admin could have created, and the same
code path serves a school year, an exam batch and a bootcamp.
"""
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core.models import Class, CourseKind, Subject
from core.tests.factories import (
    make_chapter, make_class, make_content, make_kind, make_lesson, make_quiz,
    make_student, make_subject,
)


class DynamicStructureTests(TestCase):
    """No predefined classes, subjects or kinds exist until an admin makes them."""

    def test_a_fresh_install_has_no_structure_at_all(self):
        self.assertEqual(CourseKind.objects.count(), 0)
        self.assertEqual(Class.objects.count(), 0)
        self.assertEqual(Subject.objects.count(), 0)

    def test_a_class_needs_no_kind(self):
        klass = make_class('UPSC Batch')
        self.assertIsNone(klass.kind)
        self.assertEqual(str(klass), 'UPSC Batch')

    def test_any_name_works_for_a_class(self):
        for name in ('Class 2', 'Nursery', 'IIT JEE 2027', 'Python Bootcamp', 'Kathak Level 1'):
            with self.subTest(name=name):
                self.assertEqual(make_class(name).name, name)

    def test_slugs_are_derived_from_the_name_when_blank(self):
        klass = Class.objects.create(name='NEET Foundation')
        self.assertEqual(klass.slug, 'neet-foundation')
        subject = Subject.objects.create(klass=klass, name='Organic Chemistry')
        self.assertEqual(subject.slug, 'organic-chemistry')
        self.assertEqual(CourseKind.objects.create(name='Crash Course').slug, 'crash-course')

    def test_two_classes_may_each_own_a_subject_with_the_same_slug(self):
        # Subject slugs are scoped to their class, so every class can have Maths.
        maths_a = make_subject(make_class('Class 2'), 'Maths')
        maths_b = make_subject(make_class('Class 5'), 'Maths')
        self.assertEqual(maths_a.slug, maths_b.slug)
        self.assertNotEqual(maths_a.klass_id, maths_b.klass_id)

    def test_one_class_cannot_own_two_subjects_with_the_same_slug(self):
        klass = make_class()
        make_subject(klass, 'Maths')
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_subject(klass, 'Maths')

    def test_deleting_a_kind_keeps_its_classes(self):
        # SET_NULL, not CASCADE: retiring a category must never destroy lessons.
        kind = make_kind('Bootcamp')
        klass = make_class('Python Bootcamp', kind=kind)
        kind.delete()
        klass.refresh_from_db()
        self.assertIsNone(klass.kind)
        self.assertTrue(Class.objects.filter(pk=klass.pk).exists())


class BrowsingTests(TestCase):
    def setUp(self):
        self.user = make_student()
        self.client.force_login(self.user)
        self.kind = make_kind('Coaching', color='#ef4444')
        self.klass = make_class('IIT JEE 2027', kind=self.kind)
        self.physics = make_subject(self.klass, 'Physics')
        self.chemistry = make_subject(self.klass, 'Chemistry')
        self.chapter = make_chapter(self.physics, 'Mechanics')
        self.lesson = make_lesson(self.chapter, 'Force')

    def test_dashboard_lists_classes_not_subjects(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'IIT JEE 2027')
        # The class sits under its kind's own section heading.
        self.assertContains(response, 'Coaching')
        self.assertNotContains(response, 'Physics')  # subjects live a level down
        names = [row['klass'].name for row in response.context['class_data']]
        self.assertEqual(names, ['IIT JEE 2027'])

    def test_subject_picker_lists_the_classs_subjects(self):
        response = self.client.get(reverse('subject_list', args=['iit-jee-2027']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Choose a subject')
        self.assertContains(response, 'Physics')
        self.assertContains(response, 'Chemistry')

    def test_full_drill_down(self):
        for url in (
            reverse('subject_list', args=['iit-jee-2027']),
            reverse('chapter_list', args=['iit-jee-2027', 'physics']),
            reverse('lesson_detail', args=['iit-jee-2027', 'physics', 'mechanics', 'force']),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_breadcrumb_reads_class_then_subject(self):
        response = self.client.get(
            reverse('lesson_detail', args=['iit-jee-2027', 'physics', 'mechanics', 'force'])
        )
        self.assertContains(response, 'IIT JEE 2027')
        self.assertContains(response, 'Physics')

    def test_quiz_resolves_under_class_and_subject(self):
        make_quiz(self.chapter, 'Mechanics quiz', pass_percentage=50)
        response = self.client.get(reverse('quiz', args=['iit-jee-2027', 'physics', 'mechanics']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Question 1?')

    def test_single_subject_class_skips_the_picker(self):
        self.chemistry.delete()
        response = self.client.get(reverse('subject_list', args=['iit-jee-2027']))
        self.assertRedirects(
            response, reverse('chapter_list', args=['iit-jee-2027', 'physics'])
        )

    def test_a_subject_cannot_be_reached_through_the_wrong_class(self):
        make_content('Class 2', 'Maths', 'Addition', 'Carrying over')
        response = self.client.get(reverse('chapter_list', args=['iit-jee-2027', 'maths']))
        self.assertEqual(response.status_code, 404)


class DashboardGroupingTests(TestCase):
    """Each CourseKind the admin creates becomes its own dashboard section."""

    def setUp(self):
        self.user = make_student()
        self.client.force_login(self.user)

    def groups(self):
        response = self.client.get(reverse('dashboard'))
        return response, [
            (g['kind'].name if g['kind'] else None, [c['klass'].name for c in g['classes']])
            for g in response.context['class_groups']
        ]

    def test_one_section_per_kind(self):
        school = make_kind('School', order=0)
        bootcamp = make_kind('Bootcamp', order=1)
        make_class('Class 2', kind=school)
        make_class('Class 5', kind=school)
        make_class('Python Bootcamp', kind=bootcamp)

        response, groups = self.groups()
        self.assertEqual(groups, [
            ('School', ['Class 2', 'Class 5']),
            ('Bootcamp', ['Python Bootcamp']),
        ])
        self.assertContains(response, 'School')
        self.assertContains(response, 'Bootcamp')

    def test_sections_follow_the_kind_order_field(self):
        make_class('A', kind=make_kind('Zebra', order=0))
        make_class('B', kind=make_kind('Alpha', order=1))
        _, groups = self.groups()
        self.assertEqual([name for name, _ in groups], ['Zebra', 'Alpha'])

    def test_classes_without_a_kind_land_in_a_trailing_catch_all(self):
        make_class('Python Bootcamp', kind=make_kind('Bootcamp'))
        make_class('Loose Class')
        _, groups = self.groups()
        self.assertEqual(groups, [
            ('Bootcamp', ['Python Bootcamp']),
            (None, ['Loose Class']),
        ])

    def test_no_kinds_at_all_renders_a_single_section(self):
        make_class('Class 2')
        make_class('UPSC Batch')
        response, groups = self.groups()
        self.assertEqual(groups, [(None, ['Class 2', 'UPSC Batch'])])
        self.assertContains(response, 'Your classes')

    def test_a_hidden_kind_loses_its_section_but_keeps_its_classes(self):
        hidden = make_kind('Retired', is_active=False)
        make_class('Old Batch', kind=hidden)
        response, groups = self.groups()
        self.assertEqual(groups, [(None, ['Old Batch'])])
        self.assertNotContains(response, 'Retired')
        self.assertContains(response, 'Old Batch')

    def test_a_kind_with_no_classes_gets_no_empty_section(self):
        make_kind('Workshop')
        make_class('Class 2', kind=make_kind('School'))
        _, groups = self.groups()
        self.assertEqual([name for name, _ in groups], ['School'])

    def test_grouping_does_not_change_the_totals(self):
        klass, subject, chapter, lesson = make_content('Class 2', 'Maths')
        klass.kind = make_kind('School')
        klass.save()
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['total_all'], 1)
        self.assertEqual(len(response.context['class_data']), 1)


class VisibilityTests(TestCase):
    """is_active is the admin's hide-without-deleting switch."""

    def setUp(self):
        self.user = make_student()
        self.client.force_login(self.user)
        self.klass, self.subject, self.chapter, self.lesson = make_content(
            'Class 2', 'Maths', 'Addition', 'Carrying over',
        )

    def test_inactive_class_is_hidden_from_the_dashboard(self):
        self.klass.is_active = False
        self.klass.save()
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['class_data'], [])
        self.assertNotContains(response, 'Class 2')

    def test_inactive_class_404s_on_every_learn_url(self):
        self.klass.is_active = False
        self.klass.save()
        for url in (
            reverse('subject_list', args=['class-2']),
            reverse('chapter_list', args=['class-2', 'maths']),
            reverse('lesson_detail', args=['class-2', 'maths', 'addition', 'carrying-over']),
            reverse('quiz', args=['class-2', 'maths', 'addition']),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_inactive_subject_is_hidden_but_its_class_still_works(self):
        # Two *other* subjects, so hiding one still leaves a real choice —
        # otherwise the single-subject redirect fires and the picker never renders.
        make_subject(self.klass, 'Science')
        make_subject(self.klass, 'English')
        self.subject.is_active = False
        self.subject.save()

        picker = self.client.get(reverse('subject_list', args=['class-2']))
        self.assertEqual(picker.status_code, 200)
        self.assertNotContains(picker, 'Maths')
        self.assertContains(picker, 'Science')

        self.assertEqual(
            self.client.get(reverse('chapter_list', args=['class-2', 'maths'])).status_code, 404
        )

    def test_hidden_rows_are_not_deleted(self):
        self.klass.is_active = False
        self.klass.save()
        self.assertTrue(Class.objects.filter(pk=self.klass.pk).exists())
        self.assertTrue(self.klass.subjects.exists())


class SearchScopeTests(TestCase):
    def setUp(self):
        self.user = make_student()
        self.client.force_login(self.user)
        self.klass, self.subject, self.chapter, self.lesson = make_content(
            'Python Bootcamp', 'Basics', 'Variables', 'Naming things',
        )

    def test_classes_are_searchable(self):
        response = self.client.get(reverse('search'), {'q': 'bootcamp'})
        self.assertEqual(response.context['classes_page'].paginator.count, 1)
        self.assertContains(response, reverse('subject_list', args=['python-bootcamp']))

    def test_subject_results_link_through_their_class(self):
        response = self.client.get(reverse('search'), {'q': 'basics'})
        self.assertContains(
            response, reverse('chapter_list', args=['python-bootcamp', 'basics'])
        )
        self.assertContains(response, 'Python Bootcamp')

    def test_hidden_classes_are_unreachable_via_search(self):
        self.klass.is_active = False
        self.klass.save()
        response = self.client.get(reverse('search'), {'q': 'variables'})
        self.assertEqual(response.context['total_results'], 0)


class NoHardcodedStructureTests(TestCase):
    """Guards against 6-12 (or any other structure) creeping back into the UI."""

    def setUp(self):
        self.user = make_student()
        self.client.force_login(self.user)

    def test_pages_never_invent_a_class_the_admin_did_not_create(self):
        make_content('Nursery', 'Rhymes', 'Animals', 'The cat')
        for url in (reverse('dashboard'), reverse('subject_list', args=['nursery'])):
            with self.subTest(url=url):
                body = self.client.get(url).content.decode()
                for ghost in ('Class 6', 'Class 7', 'Class 12'):
                    self.assertNotIn(ghost, body)

    def test_landing_page_makes_no_claim_about_class_numbers(self):
        self.client.logout()
        body = self.client.get(reverse('landing')).content.decode()
        self.assertNotIn('Classes 6', body)
        self.assertNotIn('6 to 12', body)

    def test_an_empty_platform_renders_without_crashing(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['class_data'], [])
        self.assertEqual(response.context['overall_percent'], 0)
        self.assertContains(response, 'Nothing here yet')
