"""core.management.commands.vercel_build: the Vercel build step."""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.context_processors import learner_count

POSTGRES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': 'x'}}
SQLITE = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}


class VercelBuildTests(SimpleTestCase):
    def run_build(self, vercel_env):
        out = StringIO()
        with mock.patch.dict('os.environ', {'VERCEL_ENV': vercel_env}), \
             mock.patch('core.management.commands.vercel_build.call_command') as inner:
            call_command('vercel_build', stdout=out)
        return inner, out.getvalue()

    def test_preview_builds_never_touch_the_database(self):
        inner, out = self.run_build('preview')
        inner.assert_not_called()
        self.assertIn('Skipping', out)

    @override_settings(DATABASES=POSTGRES)
    def test_production_build_migrates_and_creates_the_cache_table(self):
        inner, _ = self.run_build('production')
        self.assertEqual(
            [c.args[0] for c in inner.call_args_list], ['migrate', 'createcachetable']
        )

    @override_settings(DATABASES=SQLITE)
    def test_production_build_without_postgres_fails_loudly(self):
        with self.assertRaises(SystemExit):
            self.run_build('production')


class LearnerCountTests(TestCase):
    """core.context_processors.learner_count: the nav's registered-learner badge."""

    def setUp(self):
        cache.clear()

    def test_counts_students_only_excluding_staff_and_superusers(self):
        User.objects.create_user('s1', password='x')
        User.objects.create_user('s2', password='x')
        User.objects.create_user('staffer', password='x', is_staff=True)
        User.objects.create_superuser('boss', password='x')
        self.assertEqual(learner_count(RequestFactory().get('/'))['LEARNER_COUNT'], 2)

    def test_count_is_cached_between_requests(self):
        User.objects.create_user('s1', password='x')
        learner_count(RequestFactory().get('/'))
        User.objects.create_user('s2', password='x')
        self.assertEqual(learner_count(RequestFactory().get('/'))['LEARNER_COUNT'], 1)

    def test_badge_renders_in_the_nav(self):
        User.objects.create_user('s1', password='x')
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'nav-stat')
        self.assertContains(response, '<strong>1</strong>', html=False)
