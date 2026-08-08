"""Guards the data move across migrations 0005-0009 that can silently lose content.

`invert_hierarchy` (0006) swaps the top two levels and repoints every Chapter:

    academic:  Maths / Class 6    ->  Class "Class 6"  > Subject "Maths"
    course:    Python / Beginner  ->  Class "Python"   > Subject "Beginner"

The chain is split across five migrations (0005 DDL, 0006 data, 0007 DDL, 0008
data, 0009 DDL) because PostgreSQL rejects an ALTER TABLE run in the same
transaction as a preceding DML write to that table (deferred FK-constraint
triggers not yet fired) -- a restriction SQLite doesn't share, which is why the
original single-migration version passed here but crashed in production. Each
DDL-only migration's ALTER/RemoveField/DeleteModel would cascade-delete
lessons rather than move them if the data migrations ahead of it got the
ordering wrong. That is what these tests exist to catch.

Runs the real migrations through MigrationExecutor: rewind to 0004, build a
pre-migration world with the historical models, roll all the way forward to
0009, then inspect.
"""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

MIGRATE_FROM = ('core', '0004_custom_courses')
MIGRATE_TO = ('core', '0009_tighten_subject_and_retire_classlevel')


class InvertHierarchyTests(TransactionTestCase):
    # The migration rewrites schema, so the tables must survive between the
    # rewind and the roll-forward -- hence TransactionTestCase, not TestCase.
    available_apps = ['core', 'django.contrib.auth', 'django.contrib.contenttypes']

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate([MIGRATE_FROM])
        executor.loader.build_graph()
        old_apps = executor.loader.project_state([MIGRATE_FROM]).apps

        self.build_old_world(old_apps)

        executor = MigrationExecutor(connection)
        executor.migrate([MIGRATE_TO])
        self.apps = executor.loader.project_state([MIGRATE_TO]).apps

    def tearDown(self):
        # Leave the database fully migrated for whatever runs next.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate([MIGRATE_TO])

    def build_old_world(self, apps):
        Subject = apps.get_model('core', 'Subject')
        ClassLevel = apps.get_model('core', 'ClassLevel')
        Chapter = apps.get_model('core', 'Chapter')
        Lesson = apps.get_model('core', 'Lesson')

        maths = Subject.objects.create(name='Maths', slug='maths', kind='academic')
        class6 = ClassLevel.objects.create(subject=maths, level=6, slug='class-6', order=1)
        numbers = Chapter.objects.create(
            class_level=class6, title='Number System', slug='number-system', order=1,
        )
        Lesson.objects.create(
            chapter=numbers, title='Counting', slug='counting',
            order=1, youtube_video_id='dQw4w9WgXcQ',
        )

        python = Subject.objects.create(name='Python', slug='python', kind='course')
        beginner = ClassLevel.objects.create(
            subject=python, title='Beginner', slug='beginner', order=1,
        )
        ClassLevel.objects.create(subject=python, title='Advanced', slug='advanced', order=2)
        loops = Chapter.objects.create(
            class_level=beginner, title='Loops', slug='loops', order=1,
        )
        Lesson.objects.create(
            chapter=loops, title='For loops', slug='for-loop',
            order=1, youtube_video_id='dQw4w9WgXcQ',
        )

        # A subject with no levels at all, and so no chapters to lose.
        Subject.objects.create(name='Science', slug='science', kind='academic')

    # ── assertions ───────────────────────────────────────────────

    def test_no_lessons_or_chapters_are_lost(self):
        Lesson = self.apps.get_model('core', 'Lesson')
        Chapter = self.apps.get_model('core', 'Chapter')
        self.assertEqual(Lesson.objects.count(), 2)
        self.assertEqual(Chapter.objects.count(), 2)
        self.assertFalse(Chapter.objects.filter(subject__isnull=True).exists())

    def test_academic_level_becomes_the_class(self):
        Class = self.apps.get_model('core', 'Class')
        class6 = Class.objects.get(slug='class-6')
        self.assertEqual(class6.name, 'Class 6')
        self.assertEqual(class6.kind.name, 'School')
        self.assertEqual(
            list(class6.subjects.values_list('name', flat=True)), ['Maths'],
        )
        self.assertEqual(
            class6.subjects.get().chapters.get().title, 'Number System',
        )

    def test_course_subject_becomes_the_class_and_tracks_become_subjects(self):
        Class = self.apps.get_model('core', 'Class')
        python = Class.objects.get(slug='python')
        self.assertEqual(python.kind.name, 'Course')
        self.assertEqual(
            sorted(python.subjects.values_list('name', flat=True)),
            ['Advanced', 'Beginner'],
        )
        self.assertEqual(
            python.subjects.get(slug='beginner').chapters.get().title, 'Loops',
        )

    def test_a_level_less_subject_survives_as_an_empty_class(self):
        Class = self.apps.get_model('core', 'Class')
        science = Class.objects.get(slug='science')
        self.assertEqual(science.subjects.count(), 0)

    def test_the_old_top_level_subject_rows_are_gone(self):
        Subject = self.apps.get_model('core', 'Subject')
        self.assertFalse(Subject.objects.filter(klass__isnull=True).exists())
        # Only the new, class-scoped subjects remain.
        self.assertEqual(
            sorted(Subject.objects.values_list('name', flat=True)),
            ['Advanced', 'Beginner', 'Maths'],
        )
