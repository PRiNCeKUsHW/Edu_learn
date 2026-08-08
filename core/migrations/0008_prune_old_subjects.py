"""Drop the pre-migration top-level Subject rows.

Step 4 of 4a. RunPython only -- see 0005's docstring. Runs only now that
Chapter.class_level is gone (0007): deleting these earlier would cascade
Subject -> ClassLevel -> Chapter -> Lesson and destroy the content 0006 just
repointed. Cascades on to delete every remaining ClassLevel row too, since
ClassLevel.subject still CASCADEs at this point -- which is exactly what
empties that table before 0009 retires the model.
"""
from django.db import migrations


def prune_old_subjects(apps, schema_editor):
    Subject = apps.get_model('core', 'Subject')
    Subject.objects.filter(klass__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_tighten_chapter'),
    ]

    operations = [
        migrations.RunPython(prune_old_subjects, migrations.RunPython.noop),
    ]
