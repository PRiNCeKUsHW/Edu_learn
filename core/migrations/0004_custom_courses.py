import django.core.validators
from django.db import migrations, models


def backfill_class_level_slugs(apps, schema_editor):
    """
    Every row that exists at this point predates courses, so it is an academic
    class level with a non-null `level`. Give it the same slug the URL used to
    build from the integer, keeping /learn/<subject>/class-6/... resolvable.
    """
    ClassLevel = apps.get_model('core', 'ClassLevel')
    for class_level in ClassLevel.objects.all():
        class_level.slug = f'class-{class_level.level}'
        class_level.save(update_fields=['slug'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_googleaccount'),
    ]

    operations = [
        migrations.AddField(
            model_name='subject',
            name='kind',
            field=models.CharField(
                choices=[('academic', 'School Subject'), ('course', 'Course')],
                default='academic',
                help_text='School subjects are split into Classes 6–12. '
                          'Courses are split into named tracks instead.',
                max_length=20,
            ),
        ),
        migrations.AlterModelOptions(
            name='subject',
            options={'ordering': ['kind', 'name']},
        ),
        migrations.AlterField(
            model_name='classlevel',
            name='level',
            field=models.IntegerField(
                blank=True,
                choices=[(6, 'Class 6'), (7, 'Class 7'), (8, 'Class 8'), (9, 'Class 9'),
                         (10, 'Class 10'), (11, 'Class 11'), (12, 'Class 12')],
                help_text='For school subjects only. Leave blank for a course track.',
                null=True,
                validators=[django.core.validators.MinValueValidator(6),
                            django.core.validators.MaxValueValidator(12)],
            ),
        ),
        migrations.AddField(
            model_name='classlevel',
            name='title',
            field=models.CharField(
                blank=True,
                help_text='For course tracks only, e.g. "Beginner". Leave blank for a '
                          'school class — the name is derived from the level.',
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name='classlevel',
            name='order',
            field=models.PositiveIntegerField(
                default=1, help_text='Display order within the subject.'
            ),
        ),
        # Added nullable so existing rows survive, backfilled, then tightened.
        migrations.AddField(
            model_name='classlevel',
            name='slug',
            field=models.SlugField(
                help_text='URL segment. Auto-filled from the level or the title.',
                null=True,
            ),
        ),
        migrations.RunPython(
            backfill_class_level_slugs,
            # Reverse just drops the column, so there is nothing to undo.
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='classlevel',
            name='slug',
            field=models.SlugField(
                help_text='URL segment. Auto-filled from the level or the title.',
            ),
        ),
        migrations.AlterModelOptions(
            name='classlevel',
            options={'ordering': ['order', 'level']},
        ),
        migrations.AlterUniqueTogether(
            name='classlevel',
            unique_together={('level', 'subject'), ('subject', 'slug')},
        ),
    ]
