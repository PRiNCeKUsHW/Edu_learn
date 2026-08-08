"""Invert the top two levels of the hierarchy and make every level admin-defined.

Before:  Subject (Maths, Python)  ->  ClassLevel (Class 6, Beginner)  ->  Chapter
After:   Class   (Class 6, Python) ->  Subject    (Maths, Beginner)   ->  Chapter

`Subject.kind` ('academic' / 'course') is what tells us which of the two old
levels was the real class, so the remap is driven off it -- see invert_hierarchy.
"""
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models
from django.utils.text import slugify


def _level_label(class_level):
    """Inlined copy of the old ClassLevel.display_name, which no longer exists."""
    if class_level.title:
        return class_level.title
    return f'Class {class_level.level}' if class_level.level else 'Untitled'


def _unique_slug(model, base, fallback):
    slug = slugify(base) or fallback
    candidate, suffix = slug, 2
    while model.objects.filter(slug=candidate).exists():
        candidate = f'{slug}-{suffix}'
        suffix += 1
    return candidate


def invert_hierarchy(apps, schema_editor):
    """Build the Class/Subject rows and repoint every Chapter onto them.

    Deletes nothing: the old rows are pruned later, once Chapter no longer has
    a cascading FK to ClassLevel (see prune_old_subjects).
    """
    CourseKind = apps.get_model('core', 'CourseKind')
    Class = apps.get_model('core', 'Class')
    Subject = apps.get_model('core', 'Subject')
    Chapter = apps.get_model('core', 'Chapter')
    ClassLevel = apps.get_model('core', 'ClassLevel')

    kind_cache = {}
    class_cache = {}

    def kind_for(old_kind):
        if old_kind not in kind_cache:
            academic = old_kind == 'academic'
            name = 'School' if academic else 'Course'
            kind_cache[old_kind], _ = CourseKind.objects.get_or_create(
                slug=slugify(name),
                defaults={
                    'name': name,
                    'icon': 'bi-mortarboard' if academic else 'bi-collection',
                    'color': '#6366f1' if academic else '#0ea5e9',
                    'order': 0 if academic else 1,
                },
            )
        return kind_cache[old_kind]

    def class_for(name, description, icon, old_kind):
        # Keyed on the name, not the slug: _unique_slug may de-duplicate the
        # slug, and a second lookup by the original slug would then miss and
        # create a duplicate class.
        if name not in class_cache:
            class_cache[name] = Class.objects.create(
                name=name,
                slug=_unique_slug(Class, name, 'class'),
                kind=kind_for(old_kind),
                description=description,
                icon=icon or 'bi-mortarboard',
            )
        return class_cache[name]

    consumed_subject_ids = set()

    for class_level in ClassLevel.objects.select_related('subject').all():
        old_subject = class_level.subject
        consumed_subject_ids.add(old_subject.id)
        label = _level_label(class_level)

        if old_subject.kind == 'academic':
            # Maths / Class 6  ->  Class "Class 6" holding Subject "Maths"
            class_name, class_desc = label, class_level.description
            subject_name, subject_desc = old_subject.name, old_subject.description
        else:
            # Python / Beginner  ->  Class "Python" holding Subject "Beginner"
            class_name, class_desc = old_subject.name, old_subject.description
            subject_name, subject_desc = label, class_level.description

        klass = class_for(class_name, class_desc, old_subject.icon_class, old_subject.kind)

        subject_slug = slugify(subject_name) or 'general'
        subject = Subject.objects.filter(klass=klass, slug=subject_slug).first()
        if subject is None:
            subject = Subject.objects.create(
                klass=klass,
                name=subject_name,
                slug=subject_slug,
                description=subject_desc,
                icon_class=old_subject.icon_class or 'bi-book',
                order=class_level.order or 0,
            )

        Chapter.objects.filter(class_level=class_level).update(subject=subject)

    # An old subject with no levels at all (it could hold no chapters, so no
    # lessons are at stake) still represents something the admin created --
    # keep it as an empty Class rather than dropping it silently.
    for old_subject in Subject.objects.filter(klass__isnull=True):
        if old_subject.id in consumed_subject_ids:
            continue
        class_for(
            old_subject.name, old_subject.description,
            old_subject.icon_class, old_subject.kind,
        )


def prune_old_subjects(apps, schema_editor):
    """Drop the pre-migration top-level Subject rows.

    Runs only after Chapter.class_level is gone. Deleting these earlier would
    cascade Subject -> ClassLevel -> Chapter -> Lesson and destroy the content
    invert_hierarchy just repointed.
    """
    Subject = apps.get_model('core', 'Subject')
    Subject.objects.filter(klass__isnull=True).delete()


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

        # ── 3. Move the data ─────────────────────────────────────────────
        migrations.RunPython(
            invert_hierarchy,
            # Not reversible: the inversion is lossy in the other direction
            # (two old rows collapse into shapes that can't be told apart).
            migrations.RunPython.noop,
        ),

        # ── 4. Tighten Chapter, then drop its old parent ─────────────────
        migrations.AlterField(
            model_name='chapter',
            name='subject',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='chapters', to='core.subject'),
        ),
        migrations.RemoveField(model_name='chapter', name='class_level'),
        migrations.AlterUniqueTogether(
            name='chapter', unique_together={('subject', 'slug')},
        ),

        # ── 5. Now safe: no cascade path from Subject down to Lesson ─────
        migrations.RunPython(prune_old_subjects, migrations.RunPython.noop),

        migrations.AlterField(
            model_name='subject',
            name='klass',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='subjects', to='core.class', verbose_name='class'),
        ),
        migrations.RemoveField(model_name='subject', name='kind'),
        migrations.AlterModelOptions(
            name='subject', options={'ordering': ['order', 'name']},
        ),
        migrations.AlterUniqueTogether(
            name='subject', unique_together={('klass', 'slug')},
        ),

        # ── 6. Retire ClassLevel ─────────────────────────────────────────
        migrations.AlterUniqueTogether(name='classlevel', unique_together=set()),
        migrations.RemoveField(model_name='classlevel', name='subject'),
        migrations.DeleteModel(name='ClassLevel'),
    ]
