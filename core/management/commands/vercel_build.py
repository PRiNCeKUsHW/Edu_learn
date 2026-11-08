"""Build step for Vercel deployments (vercel.json -> buildCommand).

Vercel has no release phase the way the Railway Procfile did, so anything
that has to happen once per deploy happens here, during the build:

  * apply migrations, so the database matches the code being deployed;
  * create the database cache table that rate limiting uses on Vercel
    (settings.CACHES, ON_VERCEL branch).

Only production builds touch the database. Preview deployments of other
branches share the same DATABASE_URL, and migrating the live database from
an unmerged branch could break the production site.
"""
import os

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Vercel build step: migrate and create the cache table on production builds.'

    def handle(self, *args, **options):
        environment = os.environ.get('VERCEL_ENV', '')
        if environment != 'production':
            self.stdout.write(f'Skipping database setup for a "{environment or "local"}" build.')
            return

        engine = settings.DATABASES['default']['ENGINE']
        if 'postgresql' not in engine:
            # A production build without DATABASE_URL would otherwise migrate
            # a throwaway SQLite file inside the build container and report
            # success, hiding the missing variable until the first page load.
            raise SystemExit(
                'DATABASE_URL is not set for this production build. Add the Neon '
                'connection string in Vercel -> Project -> Settings -> Environment '
                'Variables, then redeploy.'
            )

        call_command('migrate', interactive=False)
        call_command('createcachetable')
        self.stdout.write(self.style.SUCCESS('Database is migrated and the cache table exists.'))
