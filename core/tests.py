"""core.management.commands.vercel_build: the Vercel build step."""
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

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
