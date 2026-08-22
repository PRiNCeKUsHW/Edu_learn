"""Settings-level tests — not app behaviour, but config logic worth locking
in without needing a live database of either kind.
"""
import re
import tempfile
from pathlib import Path
from unittest import mock

import dj_database_url
from django.test import SimpleTestCase

from .logging_config import ensure_log_dir


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


class EnsureLogDirTests(SimpleTestCase):
    """settings.py only wires up file logging when this returns True — the
    fix for LOG_DIR.mkdir() crashing the whole app at import time on a
    filesystem that turns out not to be writable (see the function's own
    docstring). Uses real temp directories rather than mocking Path.mkdir
    everywhere, since the point is proving real filesystem calls behave as
    expected, not just that the function calls mkdir."""

    def test_creates_directory_and_returns_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'logs'
            self.assertTrue(ensure_log_dir(target))
            self.assertTrue(target.is_dir())

    def test_creates_missing_parents_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'nested' / 'logs'
            self.assertTrue(ensure_log_dir(target))
            self.assertTrue(target.is_dir())

    def test_is_idempotent_when_directory_already_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'logs'
            target.mkdir()
            self.assertTrue(ensure_log_dir(target))

    def test_returns_false_instead_of_raising_when_path_is_a_file(self):
        """The realistic version of "can't create this directory" —
        something else already occupies that path."""
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / 'logs'
            blocked.write_text('not a directory')
            self.assertFalse(ensure_log_dir(blocked))

    def test_returns_false_instead_of_raising_on_permission_error(self):
        """Simulates a genuinely read-only filesystem — the scenario the
        function exists for — without needing an actual read-only mount."""
        with mock.patch.object(Path, 'mkdir', side_effect=PermissionError('Read-only file system')):
            self.assertFalse(ensure_log_dir(Path('/some/path')))


class TemplateCommentSyntaxTests(SimpleTestCase):
    """Django's `{# #}` comment is single-line only.

    Spanning one across a newline means it is never parsed as a comment: the
    whole thing renders as literal text on the page. It looks harmless in an
    editor, which is why it has slipped through twice -- once on the Progress
    page, once on the dashboard's enrolment cards. This checks every template
    in the project, including ones no test happens to render.
    """

    # Matches a {# ... #} pair non-greedily, so two comments on one line stay
    # separate rather than merging into one span that looks multi-line.
    COMMENT = re.compile(r'\{#(?:(?!#\}).)*?#\}', re.S)

    def test_no_comment_tag_spans_multiple_lines(self):
        offenders = []
        template_root = Path(__file__).resolve().parent.parent / 'templates'

        for path in sorted(template_root.rglob('*.html')):
            text = path.read_text()
            for match in self.COMMENT.finditer(text):
                if '\n' in match.group(0):
                    line = text[:match.start()].count('\n') + 1
                    offenders.append(f'{path.relative_to(template_root)}:{line}')

        self.assertEqual(
            offenders, [],
            'These {# #} comments span multiple lines and will render as '
            'visible text. Use {% comment %}...{% endcomment %} instead: '
            + ', '.join(offenders)
        )
