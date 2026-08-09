from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from curriculum.models import Class, Lesson
from quizzes.models import QuizAttempt

from .models import LessonProgress


def _watched_day_set(user):
    """Local dates on which the user marked at least one lesson watched."""
    return set(
        LessonProgress.objects
        .filter(user=user, watched=True, watched_at__isnull=False)
        .annotate(day=TruncDate('watched_at'))
        .values_list('day', flat=True)
    )


def _study_streak(day_set, today):
    """Consecutive days up to today with activity. Yesterday still counts as
    alive so the streak doesn't reset before the day is over."""
    if today in day_set:
        cursor = today
    elif (today - timedelta(days=1)) in day_set:
        cursor = today - timedelta(days=1)
    else:
        return 0

    streak = 0
    while cursor in day_set:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _resume_target(user):
    """The lesson to send the student back to: the first unwatched lesson in
    the chapter they last worked on, else that last lesson itself."""
    last = (
        LessonProgress.objects
        .filter(user=user, watched=True, watched_at__isnull=False)
        .select_related('lesson__chapter__subject__klass')
        .order_by('-watched_at')
        .first()
    )
    if last is None:
        return None

    chapter = last.lesson.chapter
    watched_ids = set(
        LessonProgress.objects
        .filter(user=user, watched=True, lesson__chapter=chapter)
        .values_list('lesson_id', flat=True)
    )
    nxt = next(
        (l for l in chapter.lessons.all() if l.id not in watched_ids),
        None,
    )
    if nxt is None:
        return last.lesson
    # `chapter` already carries subject/class from the select_related
    # above; reuse it so template URL building doesn't re-query the chain.
    nxt.chapter = chapter
    return nxt


@login_required
def dashboard(request):
    # One aggregate query for every class instead of 2 per class. Only active
    # classes are offered; is_active is the admin's hide-without-deleting switch.
    classes = Class.objects.filter(is_active=True).select_related('kind').annotate(
        total_lessons=Count('subjects__chapters__lessons', distinct=True),
        watched_lessons=Count(
            'subjects__chapters__lessons__progress',
            filter=Q(
                subjects__chapters__lessons__progress__user=request.user,
                subjects__chapters__lessons__progress__watched=True,
            ),
            distinct=True,
        ),
        subject_count=Count('subjects', filter=Q(subjects__is_active=True), distinct=True),
    )

    class_data = []
    # Every CourseKind the admin creates becomes its own dashboard section.
    # Keyed by kind id, so the grouping is built in the same pass as the cards.
    grouped = {}
    ungrouped = []
    total_all = watched_all = 0

    for klass in classes:
        total = klass.total_lessons
        watched = klass.watched_lessons
        total_all += total
        watched_all += watched
        card = {
            'klass': klass,
            'total_lessons': total,
            'watched_lessons': watched,
            'subject_count': klass.subject_count,
            'percent': round((watched / total) * 100) if total else 0,
        }
        class_data.append(card)

        # A hidden kind is treated like no kind at all: is_active means "don't
        # show this to students", and that has to apply to the heading too.
        # The classes themselves still appear — they have their own is_active.
        kind = klass.kind if (klass.kind and klass.kind.is_active) else None
        if kind is None:
            ungrouped.append(card)
        else:
            grouped.setdefault(kind.id, {'kind': kind, 'classes': []})['classes'].append(card)

    class_groups = sorted(
        grouped.values(), key=lambda group: (group['kind'].order, group['kind'].name)
    )
    if ungrouped:
        # Trailing catch-all, so a platform with no kinds at all still renders
        # exactly one section.
        class_groups.append({'kind': None, 'classes': ungrouped})

    today = timezone.localdate()
    day_set = _watched_day_set(request.user)

    return render(request, 'progress/dashboard.html', {
        'class_data': class_data,
        'class_groups': class_groups,
        'overall_percent': round((watched_all / total_all) * 100) if total_all else 0,
        'watched_all': watched_all,
        'total_all': total_all,
        'streak': _study_streak(day_set, today),
        # Oldest-first so the dot strip reads left to right, ending today.
        'week_activity': [
            {'day': today - timedelta(days=offset),
             'active': (today - timedelta(days=offset)) in day_set}
            for offset in range(6, -1, -1)
        ],
        'quizzes_passed': QuizAttempt.objects.filter(
            user=request.user, passed=True
        ).values('quiz').distinct().count(),
        'resume_lesson': _resume_target(request.user),
    })


@login_required
@require_POST
def mark_watched(request, lesson_id):
    lesson = get_object_or_404(Lesson, id=lesson_id)
    progress, _ = LessonProgress.objects.get_or_create(
        user=request.user, lesson=lesson
    )
    progress.watched = not progress.watched
    progress.watched_at = timezone.now() if progress.watched else None
    progress.save()
    return JsonResponse({'watched': progress.watched})
