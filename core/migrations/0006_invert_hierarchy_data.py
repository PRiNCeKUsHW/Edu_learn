"""Move the data: build Class/Subject rows and repoint every Chapter onto them.

Step 2 of 4 (see 0005's docstring for why this is split across several
migrations). This one is RunPython only -- no DDL -- so on PostgreSQL its
transaction commits cleanly, and the FK-validation triggers for everything it
just wrote have fully fired before 0007's ALTER TABLE starts.

`Subject.kind` ('academic' / 'course') is what tells us which of the two old
levels was the real class, so the remap is driven off it.
"""
from django.db import migrations
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
    a cascading FK to ClassLevel (see 0008's prune_old_subjects).
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


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_dynamic_hierarchy'),
    ]

    operations = [
        migrations.RunPython(
            invert_hierarchy,
            # Not reversible: the inversion is lossy in the other direction
            # (two old rows collapse into shapes that can't be told apart).
            migrations.RunPython.noop,
        ),
    ]
