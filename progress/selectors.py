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

from curriculum.models import Class, Lesson
from quizzes.models import QuizAttempt

from .models import Enrollment, LessonProgress

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


def enrolled_class_ids(user):
    """Ids of the classes this user has enrolled in."""
    return set(
        Enrollment.objects.filter(user=user).values_list('klass_id', flat=True)
    )


def annotate_class_progress(user, enrolled_only=False):
    """Active classes, each carrying this user's watch counts.

    With enrolled_only, narrowed to the courses the user actually enrolled in.

    One aggregate query for every class instead of 2 per class. `distinct=True`
    is load-bearing: the subjects->chapters->lessons join fans out, so a plain
    Count would multiply rows. Progress rows are created lazily when a lesson
    page is opened, so watched=True is what makes the count mean anything.
    """
    classes = Class.objects.filter(is_active=True)
    if enrolled_only:
        # A pk__in subquery rather than .filter(enrollments__user=user): this
        # queryset already carries three Count(distinct=True) annotations over
        # subjects->chapters->lessons, and another join is a needless fan-out
        # risk for a filter that selects at most one enrollment row per class.
        classes = classes.filter(pk__in=enrolled_class_ids(user))

    return classes.select_related('kind').annotate(
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


def class_progress_rows(user, enrolled_only=False):
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
        for klass in annotate_class_progress(user, enrolled_only) if klass.total_lessons
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


def study_minutes(user):
    """Total runtime of the lessons this user has marked watched."""
    total = Lesson.objects.filter(
        progress__user=user, progress__watched=True
    ).aggregate(total=Sum('duration_minutes'))['total']
    return total or 0
