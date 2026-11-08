"""Enrol existing students in the courses they were already studying.

Enrollment arrived empty, and the dashboard and Progress page now show only
enrolled courses, so without this every existing student would land on "You
haven't enrolled in a course yet" despite having watched lessons and taken
quizzes. A student counts as studying a class if they have any lesson
progress or any quiz attempt in it.

Data only, in a migration of its own: on PostgreSQL the FK constraints are
DEFERRABLE INITIALLY DEFERRED, and mixing RunPython with schema changes in
one transaction has failed in production before ("pending trigger events").
"""
from django.db import migrations


def enrol_existing_students(apps, schema_editor):
    Enrollment = apps.get_model('progress', 'Enrollment')
    LessonProgress = apps.get_model('progress', 'LessonProgress')
    QuizAttempt = apps.get_model('quizzes', 'QuizAttempt')

    pairs = set(
        LessonProgress.objects.values_list('user_id', 'lesson__chapter__subject__klass_id')
    )
    pairs |= set(
        QuizAttempt.objects.values_list('user_id', 'quiz__chapter__subject__klass_id')
    )
    already = set(Enrollment.objects.values_list('user_id', 'klass_id'))

    Enrollment.objects.bulk_create(
        [Enrollment(user_id=user_id, klass_id=klass_id)
         for user_id, klass_id in sorted(pairs - already)],
        batch_size=500,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('progress', '0002_enrollment'),
        ('quizzes', '0002_quizanswer'),
    ]

    operations = [
        # Reverse is a no-op: the enrollments it created are indistinguishable
        # from ones students made themselves, so undoing it can't safely
        # delete anything.
        migrations.RunPython(enrol_existing_students, migrations.RunPython.noop),
    ]
