"""Read-only queries behind the student-facing progress screens.

These live outside views.py because three call sites need them: the home
dashboard, the student's own Progress page, and the staff report card in
admin_panel. Every function takes a `user` rather than a request, so the
staff report can ask the same questions about someone else.
"""
from datetime import timedelta

from django.db.models import Avg, Count, F, FloatField, Max, Q, Sum
from django.db.models.expressions import ExpressionWrapper
from django.db.models.functions import TruncDate

from curriculum.models import Chapter, Class, Lesson
from curriculum.selectors import attach_positions, latest_lessons
from quizzes.models import QuizAttempt

from .models import LessonProgress

# score/total as a percentage the database can average over. QuizAttempt
# .percentage is a Python property, so it can't be used in an aggregate --
# this is the SQL-side equivalent. Callers must exclude total=0 rows first.
_ATTEMPT_PERCENT = ExpressionWrapper(
    F('score') * 100.0 / F('total'), output_field=FloatField()
)


def watched_day_set(user):
    """Local dates on which the user marked at least one lesson watched."""
    return set(
        LessonProgress.objects
        .filter(user=user, watched=True, watched_at__isnull=False)
        .annotate(day=TruncDate('watched_at'))
        .values_list('day', flat=True)
    )


def study_streak(day_set, today):
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


def week_activity(day_set, today, days=7):
    """Oldest-first day flags, so a dot strip reads left to right ending today."""
    return [
        {'day': today - timedelta(days=offset),
         'active': (today - timedelta(days=offset)) in day_set}
        for offset in range(days - 1, -1, -1)
    ]


def annotate_class_progress(user):
    """Active classes, each carrying this user's watch counts.

    One aggregate query for every class instead of 2 per class. `distinct=True`
    is load-bearing: the subjects->chapters->lessons join fans out, so a plain
    Count would multiply rows. Progress rows are created lazily when a lesson
    page is opened, so watched=True is what makes the count mean anything.
    """
    return Class.objects.filter(is_active=True).select_related('kind').annotate(
        total_lessons=Count('subjects__chapters__lessons', distinct=True),
        watched_lessons=Count(
            'subjects__chapters__lessons__progress',
            filter=Q(
                subjects__chapters__lessons__progress__user=user,
                subjects__chapters__lessons__progress__watched=True,
            ),
            distinct=True,
        ),
        subject_count=Count('subjects', filter=Q(subjects__is_active=True), distinct=True),
    )


def class_progress_rows(user):
    """Per-class completion rows for a report card.

    Classes with no lessons are dropped rather than shown at 0% -- an empty
    class is an authoring gap, not something the student failed to watch.
    """
    return [
        {
            'klass': klass,
            'total_lessons': klass.total_lessons,
            'watched_lessons': klass.watched_lessons,
            'percent': round((klass.watched_lessons / klass.total_lessons) * 100)
                       if klass.total_lessons else 0,
        }
        for klass in annotate_class_progress(user) if klass.total_lessons
    ]


def quiz_stats(user):
    """Headline marks for one student.

    `quizzes_passed` and `quizzes_given` count distinct quizzes, not rows, so
    retakes of the same quiz don't inflate them -- the home dashboard has
    always reported passes this way. `attempts_count` is the raw row count,
    which is the one number that should grow on every retake.
    """
    attempts = QuizAttempt.objects.filter(user=user)
    # A zero-question quiz stores total=0. SQLite quietly returns NULL for
    # x/0, but PostgreSQL -- what DATABASE_URL selects in production -- raises
    # division_by_zero and would 500 the page, so the rows are excluded here
    # rather than left to the database to tolerate.
    scored = attempts.exclude(total=0).aggregate(
        avg=Avg(_ATTEMPT_PERCENT), best=Max(_ATTEMPT_PERCENT)
    )
    return {
        'attempts_count': attempts.count(),
        'quizzes_given': attempts.values('quiz').distinct().count(),
        'quizzes_passed': attempts.filter(passed=True).values('quiz').distinct().count(),
        'avg_percent': round(scored['avg']) if scored['avg'] is not None else 0,
        'best_percent': round(scored['best']) if scored['best'] is not None else 0,
    }


def recently_viewed(user, limit=6):
    """The lessons this user opened most recently, newest first.

    Returns LessonProgress rows (so the template also knows which ones are
    watched), each with its lesson's episode position attached.
    """
    rows = list(
        LessonProgress.objects
        .filter(
            user=user,
            last_viewed_at__isnull=False,
            lesson__chapter__subject__is_active=True,
            lesson__chapter__subject__klass__is_active=True,
        )
        .select_related('lesson__chapter__subject__klass')
        .order_by('-last_viewed_at')[:limit]
    )
    attach_positions([row.lesson for row in rows])
    return rows


def recommended_lessons(user, limit=6, exclude_ids=()):
    """"Up next": the next unwatched lessons in the chapters this user has
    been working through, most recently touched chapter first, at most two
    per chapter so one long chapter can't fill the whole rail.

    A student with no history yet -- or who has finished everything they
    started -- is topped up with the newest lessons on the site instead, so
    the rail is never empty while there is content to offer.
    """
    exclude_ids = set(exclude_ids)
    touched = (
        LessonProgress.objects
        .filter(user=user)
        .exclude(last_viewed_at__isnull=True, watched_at__isnull=True)
        .values_list('lesson__chapter_id', 'last_viewed_at', 'watched_at')
    )
    recency = {}
    for chapter_id, viewed, watched in touched:
        stamp = max(t for t in (viewed, watched) if t is not None)
        if chapter_id not in recency or stamp > recency[chapter_id]:
            recency[chapter_id] = stamp

    watched_ids = set(
        LessonProgress.objects.filter(user=user, watched=True).values_list('lesson_id', flat=True)
    )

    chapters = {
        chapter.id: chapter
        for chapter in Chapter.objects.filter(
            id__in=recency,
            subject__is_active=True,
            subject__klass__is_active=True,
        ).select_related('subject__klass').prefetch_related('lessons')
    }

    picks = []
    for chapter_id in sorted(chapters, key=recency.get, reverse=True):
        chapter = chapters[chapter_id]
        taken = 0
        for lesson in chapter.lessons.all():
            if lesson.id in watched_ids or lesson.id in exclude_ids:
                continue
            # Reuse the chapter already carrying subject/class, so building
            # the lesson URL in the template doesn't query the chain again.
            lesson.chapter = chapter
            picks.append(lesson)
            taken += 1
            if taken == 2 or len(picks) == limit:
                break
        if len(picks) == limit:
            break

    if len(picks) < limit:
        seen = exclude_ids | watched_ids | {lesson.id for lesson in picks}
        picks += latest_lessons(limit - len(picks), exclude_ids=seen)

    return attach_positions(picks)


def study_minutes(user):
    """Total runtime of the lessons this user has marked watched."""
    total = Lesson.objects.filter(
        progress__user=user, progress__watched=True
    ).aggregate(total=Sum('duration_minutes'))['total']
    return total or 0
