import logging

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django_ratelimit.decorators import ratelimit

from discussions.forms import CommentForm
from discussions.models import Comment
from progress.models import LessonProgress

from .models import Chapter, Class, Lesson, Subject

logger = logging.getLogger(__name__)


@login_required
def subject_list(request, class_slug):
    klass = get_object_or_404(Class, slug=class_slug, is_active=True)
    subjects = list(klass.subjects.filter(is_active=True).annotate(
        chapter_count=Count('chapters', distinct=True),
        lesson_count=Count('chapters__lessons', distinct=True),
        watched_count=Count(
            'chapters__lessons__progress',
            filter=Q(
                chapters__lessons__progress__user=request.user,
                chapters__lessons__progress__watched=True,
            ),
            distinct=True,
        ),
    ))

    # A class with a single subject has nothing to choose between — send the
    # student straight to its chapters instead of rendering a one-card picker.
    if len(subjects) == 1:
        return redirect('chapter_list', class_slug=klass.slug, subject_slug=subjects[0].slug)

    subject_data = [{
        'subject': subject,
        'chapter_count': subject.chapter_count,
        'lesson_count': subject.lesson_count,
        'watched_count': subject.watched_count,
        'percent': round((subject.watched_count / subject.lesson_count) * 100)
                   if subject.lesson_count else 0,
    } for subject in subjects]

    return render(request, 'curriculum/subject_list.html', {
        'klass': klass,
        'subject_data': subject_data,
    })


def _get_subject(class_slug, subject_slug):
    """Resolve Class → Subject for the drill-down views, active rows only."""
    klass = get_object_or_404(Class, slug=class_slug, is_active=True)
    # Scoped through `klass.subjects` rather than
    # get_object_or_404(Subject, klass=klass, ...): that helper's own first
    # parameter is named `klass`, so passing the FK by keyword collides with
    # it and raises TypeError before any query runs.
    subject = get_object_or_404(klass.subjects, slug=subject_slug, is_active=True)
    return klass, subject


@login_required
def chapter_list(request, class_slug, subject_slug):
    klass, subject = _get_subject(class_slug, subject_slug)
    chapters = Chapter.objects.filter(subject=subject).prefetch_related('lessons')

    watched_ids = set(
        LessonProgress.objects.filter(
            user=request.user, watched=True
        ).values_list('lesson_id', flat=True)
    )

    return render(request, 'curriculum/chapter_list.html', {
        'klass': klass,
        'subject': subject,
        'chapters': chapters,
        'watched_ids': watched_ids,
    })


@login_required
# method='POST' means only the comment-post branch below is ever counted or
# limited — GET (the actual lesson page view) is untouched, so normal
# browsing has no rate limit at all. key='user' rather than 'ip' since
# @login_required already guarantees an authenticated request; this also
# means one student on a shared/NAT'd IP (a school network, for instance)
# can't be rate-limited by classmates posting at the same time.
@ratelimit(key='user', rate='10/m', method='POST', block=False)
def lesson_detail(request, class_slug, subject_slug, chapter_slug, lesson_slug):
    klass, subject = _get_subject(class_slug, subject_slug)
    chapter = get_object_or_404(Chapter, subject=subject, slug=chapter_slug)
    lesson = get_object_or_404(Lesson, chapter=chapter, slug=lesson_slug)

    progress, _ = LessonProgress.objects.get_or_create(
        user=request.user, lesson=lesson
    )

    resources = lesson.resources.all()
    # Comment posting stays inline here rather than its own discussions view:
    # extracting it would change the form's POST target and add behavioral
    # risk for no real gain, since a comment always redirects back to this
    # same lesson page either way.
    comments = lesson.comments.filter(parent=None).prefetch_related('replies__user')
    comment_form = CommentForm()

    if request.method == 'POST' and 'comment_body' in request.POST:
        if getattr(request, 'limited', False):
            logger.warning('Comment rate limit hit by user %r on lesson %s', request.user.username, lesson.id)
            messages.error(
                request,
                "You're posting comments too quickly. Please wait a moment and try again.",
            )
            return redirect(request.path)
        comment_form = CommentForm({'body': request.POST.get('comment_body')})
        if comment_form.is_valid():
            comment = comment_form.save(commit=False)
            comment.lesson = lesson
            comment.user = request.user
            parent_id = request.POST.get('parent_id')
            if parent_id:
                # Scope the parent to this lesson, and to a top-level comment.
                # Unscoped, any comment id would be accepted, letting a reply be
                # attached under a comment on a different lesson entirely.
                comment.parent = get_object_or_404(
                    Comment, id=parent_id, lesson=lesson, parent=None
                )
            comment.save()
            messages.success(request, 'Comment posted!')
            return redirect(request.path)

    all_lessons = list(chapter.lessons.all())
    current_idx = next((i for i, l in enumerate(all_lessons) if l.id == lesson.id), 0)
    prev_lesson = all_lessons[current_idx - 1] if current_idx > 0 else None
    next_lesson = all_lessons[current_idx + 1] if current_idx < len(all_lessons) - 1 else None

    # A reverse accessor from quizzes.Quiz's OneToOneField(related_name='quiz')
    # -- resolved purely through the ORM once `quizzes` is installed, no
    # import needed here.
    quiz = getattr(chapter, 'quiz', None)

    return render(request, 'curriculum/lesson_detail.html', {
        'klass': klass,
        'subject': subject,
        'chapter': chapter,
        'lesson': lesson,
        'progress': progress,
        'resources': resources,
        'comments': comments,
        'comment_form': comment_form,
        'prev_lesson': prev_lesson,
        'next_lesson': next_lesson,
        'quiz': quiz,
    })


# ─────────────────────────────────────────────
# SEARCH
# ─────────────────────────────────────────────

SEARCH_RESULTS_PER_PAGE = 10


def _search_page(request, queryset, param_name):
    """Slice one section's results into its own page. Subjects, Chapters and
    Lessons paginate independently (distinct query params) so paging one
    section doesn't reset the page a student is already on in another."""
    return Paginator(queryset, SEARCH_RESULTS_PER_PAGE).get_page(request.GET.get(param_name))


def _other_pager_query(request, exclude_param):
    """The current querystring minus one section's own page param, so that
    section's pager links carry `q` and the other two sections' page numbers
    forward without stepping on its own. Same pattern as
    admin_panel._paginated(), generalized to three independent pagers."""
    params = request.GET.copy()
    params.pop(exclude_param, None)
    encoded = params.urlencode()
    return f'&{encoded}' if encoded else ''


@login_required
def search_view(request):
    """Case-insensitive, partial-match search across the curriculum. Plain
    `icontains` rather than a full-text search engine: at this project's
    scale (a K-12 syllabus — hundreds, not millions, of rows) a substring
    filter over a few thousand rows is already fast, and reaching for
    Postgres trigram indexes or a search service here would be solving a
    scale problem this project doesn't have yet. If the catalog grows by
    orders of magnitude, that's the first thing to add.
    """
    query = request.GET.get('q', '').strip()

    if query:
        # Every level is searchable, and every level filters on is_active so a
        # hidden class can't be reached through the search box.
        classes = Class.objects.filter(
            Q(name__icontains=query) | Q(description__icontains=query),
            is_active=True,
        ).select_related('kind').order_by('order', 'name')
        subjects = Subject.objects.filter(
            Q(name__icontains=query) | Q(description__icontains=query),
            is_active=True, klass__is_active=True,
        ).select_related('klass').order_by('klass__name', 'order', 'name')
        chapters = Chapter.objects.select_related('subject__klass').filter(
            Q(title__icontains=query) | Q(description__icontains=query),
            subject__is_active=True, subject__klass__is_active=True,
        ).order_by('subject__klass__name', 'subject__order', 'order')
        lessons = Lesson.objects.select_related('chapter__subject__klass').filter(
            Q(title__icontains=query) | Q(description__icontains=query),
            chapter__subject__is_active=True, chapter__subject__klass__is_active=True,
        ).order_by('chapter__subject__klass__name', 'chapter__order', 'order')
    else:
        classes = Class.objects.none()
        subjects = Subject.objects.none()
        chapters = Chapter.objects.none()
        lessons = Lesson.objects.none()

    classes_page = _search_page(request, classes, 'klpage')
    subjects_page = _search_page(request, subjects, 'spage')
    chapters_page = _search_page(request, chapters, 'cpage')
    lessons_page = _search_page(request, lessons, 'lpage')

    return render(request, 'curriculum/search_results.html', {
        'query': query,
        'classes_page': classes_page,
        'classes_pager_query': _other_pager_query(request, 'klpage'),
        'subjects_page': subjects_page,
        'subjects_pager_query': _other_pager_query(request, 'spage'),
        'chapters_page': chapters_page,
        'chapters_pager_query': _other_pager_query(request, 'cpage'),
        'lessons_page': lessons_page,
        'lessons_pager_query': _other_pager_query(request, 'lpage'),
        'total_results': (
            classes_page.paginator.count
            + subjects_page.paginator.count
            + chapters_page.paginator.count
            + lessons_page.paginator.count
        ),
    })
