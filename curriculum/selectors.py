"""Read-only lesson queries shared by the landing page, the dashboard and the
lesson page.

Kept out of views.py because three apps call them (accounts' landing,
progress' dashboard, curriculum's own lesson page).
"""
from .models import Lesson

# A lesson is only offered to students when every level above it is live:
# hiding a class or subject in the panel has to hide its lessons everywhere.
_LIVE = {
    'chapter__subject__is_active': True,
    'chapter__subject__klass__is_active': True,
}


def live_lessons():
    """Lessons whose subject and class are both active, with the whole
    parent chain joined so templates can build lesson URLs without
    re-querying per card."""
    return Lesson.objects.filter(**_LIVE).select_related('chapter__subject__klass')


def latest_lessons(limit=8, exclude_ids=()):
    """Newest lessons first: what the landing page and an empty "Up next"
    fall back to."""
    qs = live_lessons().order_by('-created_at', '-id')
    if exclude_ids:
        qs = qs.exclude(id__in=exclude_ids)
    return attach_positions(list(qs[:limit]))


def attach_positions(lessons):
    """Set `ep_index` and `ep_total` on each lesson -- its place within its own
    chapter, e.g. 8 and 9 for "8/9". That pair is the episode marker the
    channel prints on every thumbnail, and the lesson cards repeat it.

    One query for every chapter involved rather than one per card.
    """
    chapter_ids = {lesson.chapter_id for lesson in lessons}
    if not chapter_ids:
        return lessons

    order = {}
    rows = (
        Lesson.objects.filter(chapter_id__in=chapter_ids)
        .order_by('chapter_id', 'order', 'id')
        .values_list('chapter_id', 'id')
    )
    for chapter_id, lesson_id in rows:
        order.setdefault(chapter_id, []).append(lesson_id)

    for lesson in lessons:
        siblings = order.get(lesson.chapter_id, [])
        lesson.ep_total = len(siblings)
        lesson.ep_index = siblings.index(lesson.id) + 1 if lesson.id in siblings else None
    return lessons
