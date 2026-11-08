"""The two pages a logged-out visitor can see: the landing page and About."""
from django.test import TestCase, override_settings
from django.urls import reverse

from curriculum.tests.factories import make_chapter, make_class, make_lesson, make_student, make_subject


class AboutPageTests(TestCase):
    def test_is_public(self):
        self.assertEqual(self.client.get(reverse('about')).status_code, 200)

    @override_settings(YOUTUBE_CHANNEL_URL='https://www.youtube.com/@ExampleChannel')
    def test_links_to_the_configured_channel(self):
        self.assertContains(self.client.get(reverse('about')), 'https://www.youtube.com/@ExampleChannel')

    def test_has_a_contact_section(self):
        self.assertContains(self.client.get(reverse('about')), 'id="contact"')

    def test_lesson_count_ignores_hidden_classes(self):
        hidden = make_class('Old Batch', is_active=False)
        make_lesson(make_chapter(make_subject(hidden)))
        self.assertEqual(self.client.get(reverse('about')).context['lesson_count'], 0)


class LandingPageTests(TestCase):
    def test_lists_published_classes_and_latest_lessons(self):
        klass = make_class('Class 9')
        lesson = make_lesson(make_chapter(make_subject(klass, 'Mathematics')), 'Varignon')
        response = self.client.get(reverse('landing'))
        self.assertContains(response, 'Class 9')
        self.assertIn(lesson, response.context['latest_lessons'])

    def test_hidden_class_is_not_offered(self):
        make_class('Retired', is_active=False)
        self.assertNotContains(self.client.get(reverse('landing')), 'Retired')

    def test_logged_in_visitor_is_sent_to_the_dashboard(self):
        self.client.force_login(make_student())
        self.assertRedirects(self.client.get(reverse('landing')), reverse('dashboard'))
