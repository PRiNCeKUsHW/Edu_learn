"""Settings-level tests — not app behaviour, but config logic worth locking
in without needing a live database of either kind.
"""
import dj_database_url
from django.test import SimpleTestCase


class DatabaseUrlParsingTests(SimpleTestCase):
    """Confirms DATABASE_URL parses to what settings.py expects, without
    requiring an actual Postgres connection. Live connectivity (migrations,
    the full test suite, and a real HTTP session) was verified separately
    against a real local PostgreSQL 17 instance during this change."""

    def test_postgres_url_parses_to_postgres_engine(self):
        parsed = dj_database_url.parse(
            'postgres://appuser:secret@db.example.com:5432/edulearn',
            conn_max_age=600,
            conn_health_checks=True,
        )
        self.assertEqual(parsed['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(parsed['NAME'], 'edulearn')
        self.assertEqual(parsed['USER'], 'appuser')
        self.assertEqual(parsed['PASSWORD'], 'secret')
        self.assertEqual(parsed['HOST'], 'db.example.com')
        self.assertEqual(parsed['PORT'], 5432)
        self.assertEqual(parsed['CONN_MAX_AGE'], 600)
        self.assertTrue(parsed['CONN_HEALTH_CHECKS'])

    def test_sqlite_memory_url_still_parses(self):
        """Not what settings.py uses (it takes the plain-dict branch
        instead), but proves the parser itself isn't Postgres-only —
        DATABASE_URL could point at SQLite too if someone wanted that."""
        parsed = dj_database_url.parse('sqlite:///./test.db')
        self.assertEqual(parsed['ENGINE'], 'django.db.backends.sqlite3')
