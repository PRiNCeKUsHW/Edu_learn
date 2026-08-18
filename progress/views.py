from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from curriculum.models import Lesson
from quizzes.models import QuizAttempt

from .models import LessonProgress
from .selectors import (
    annotate_class_progress,
    class_progress_rows,
    quiz_stats,
    study_minutes,
    study_streak,
    watched_day_set,
    week_activity,
)


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
    classes = annotate_class_progress(request.user)

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
    day_set = watched_day_set(request.user)

    return render(request, 'progress/dashboard.html', {
        'class_data': class_data,
        'class_groups': class_groups,
        'overall_percent': round((watched_all / total_all) * 100) if total_all else 0,
        'watched_all': watched_all,
        'total_all': total_all,
        'streak': study_streak(day_set, today),
        'week_activity': week_activity(day_set, today),
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


@login_required
def my_progress(request):
    """The student's own report card: how far through each class they are,
    and every quiz mark they've earned.

    The home dashboard answers "what should I do next"; this answers "how am
    I doing". Deliberately shows the full attempt history rather than the
    latest attempt per quiz, so a student can see themselves improving across
    retakes -- the same reasoning behind the staff-side report.
    """
    today = timezone.localdate()
    day_set = watched_day_set(request.user)
    class_progress = class_progress_rows(request.user)

    watched_all = sum(row['watched_lessons'] for row in class_progress)
    total_all = sum(row['total_lessons'] for row in class_progress)

    return render(request, 'progress/my_progress.html', {
        'class_progress': class_progress,
        # select_related spans quiz -> chapter -> subject -> class because the
        # history list names the class for every row; without it the page runs
        # four extra queries per attempt.
        'attempts': QuizAttempt.objects.filter(user=request.user).select_related(
            'quiz__chapter__subject__klass'
        ),
        'stats': quiz_stats(request.user),
        'study_minutes': study_minutes(request.user),
        'watched_all': watched_all,
        'total_all': total_all,
        'overall_percent': round((watched_all / total_all) * 100) if total_all else 0,
        'streak': study_streak(day_set, today),
        'week_activity': week_activity(day_set, today),
    })
