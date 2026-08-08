"""Widen the schema so both the old and new hierarchy shapes can coexist.

Before:  Subject (Maths, Python)  ->  ClassLevel (Class 6, Beginner)  ->  Chapter
After:   Class   (Class 6, Python) ->  Subject    (Maths, Beginner)   ->  Chapter

This is step 1 of 4 (see 0006/0007/0008/0009). Splitting what was originally
one migration into several is *required* on PostgreSQL, not a style choice:
Postgres creates FK constraints DEFERRABLE INITIALLY DEFERRED, so a
constraint's validation trigger only fires at COMMIT. Doing a data write
(RunPython) and then, in the *same* migration/transaction, an ALTER TABLE on
that same table raises `OperationalError: cannot ALTER TABLE "..." because it
has pending trigger events` -- SQLite has no such restriction, which is why
the original single-file version passed locally and only crashed against the
production Postgres database. Each of these four migrations is DDL-only or
RunPython-only, never both against the same table, so each one commits
cleanly before the next begins.
"""
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_custom_courses'),
    ]

    operations = [
        # ── 1. The two new admin-defined levels ──────────────────────────
        migrations.CreateModel(
            name='CourseKind',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('slug', models.SlugField(unique=True)),
                ('description', models.TextField(blank=True)),
                ('icon', models.CharField(
                    default='bi-collection', max_length=50,
                    help_text="Bootstrap Icon class e.g. 'bi-mortarboard'")),
                ('color', models.CharField(
                    default='#6366f1', max_length=7,
                    help_text="Hex colour for this kind's badge, e.g. #6366f1.",
                    validators=[django.core.validators.RegexValidator(
                        message='Enter a 6-digit hex colour, e.g. #6366f1.',
                        regex='^#[0-9A-Fa-f]{6}$')])),
                ('is_active', models.BooleanField(default=True)),
                ('order', models.PositiveIntegerField(default=0, help_text='Display order.')),
            ],
            options={'ordering': ['order', 'name']},
        ),
        migrations.CreateModel(
            name='Class',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150)),
                ('slug', models.SlugField(
                    unique=True, help_text='URL segment. Auto-filled from the name.')),
                ('description', models.TextField(blank=True)),
                ('thumbnail', models.ImageField(
                    blank=True, null=True, upload_to='class_thumbnails/%Y/%m/',
                    validators=[django.core.validators.FileExtensionValidator(
                        ['png', 'jpg', 'jpeg', 'webp'])])),
                ('icon', models.CharField(
                    default='bi-mortarboard', max_length=50,
                    help_text='Bootstrap Icon class, used when there is no thumbnail.')),
                ('is_active', models.BooleanField(
                    default=True,
                    help_text='Uncheck to hide from students without deleting.')),
                ('order', models.PositiveIntegerField(default=0, help_text='Display order.')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('kind', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='classes', to='core.coursekind',
                    help_text='Optional grouping, e.g. School or Bootcamp.')),
            ],
            options={'ordering': ['order', 'name'], 'verbose_name_plural': 'classes'},
        ),

        # ── 2. Widen Subject/Chapter so both shapes can coexist ──────────
        migrations.AlterField(
            model_name='subject',
            name='slug',
            field=models.SlugField(help_text='URL segment. Auto-filled from the name.'),
        ),
        migrations.AddField(
            model_name='subject',
            name='klass',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='subjects', to='core.class', verbose_name='class'),
        ),
        migrations.AddField(
            model_name='subject',
            name='is_active',
            field=models.BooleanField(
                default=True, help_text='Uncheck to hide from students without deleting.'),
        ),
        migrations.AddField(
            model_name='subject',
            name='order',
            field=models.PositiveIntegerField(
                default=0, help_text='Display order within the class.'),
        ),
        # Cleared now so Chapter.class_level can be dropped further down.
        migrations.AlterUniqueTogether(name='chapter', unique_together=set()),
        migrations.AddField(
            model_name='chapter',
            name='subject',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='chapters', to='core.subject'),
        ),
    ]
