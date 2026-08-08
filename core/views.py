import logging
import secrets
from datetime import datetime, timedelta

from django.shortcuts import render, get_object_or_404, redirect
from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from .forms import CommentForm, GoogleCompleteProfileForm
from .google_oauth import (
    GoogleOAuthError, build_authorization_url, exchange_code_for_claims, generate_state,
)
from .models import (
    Chapter, Class, Comment, GoogleAccount, Lesson,
    LessonProgress, Quiz, QuizAttempt, Subject,
)
from .ratelimit import get_client_ip

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# PUBLIC VIEWS
# ─────────────────────────────────────────────

def landing(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'core/landing.html')


# New accounts are created through Google only (see google_complete_profile_view)
# -- there is deliberately no username/email/password form or POST handler
# here anymore. Signup abuse is bounded on the Google side instead: by
# REGISTRATION_RATE_LIMIT on google_complete_profile_view, the actual
# account-creation endpoint.
def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'core/register.html', {
        'google_oauth_configured': settings.GOOGLE_OAUTH_CONFIGURED,
    })


@ratelimit(key='ip', rate=settings.LOGIN_RATE_LIMIT, method='POST', block=False)
def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if getattr(request, 'limited', False):
        logger.warning(
            'Login rate limit hit from %s (username attempted: %r)',
            get_client_ip(request), request.POST.get('username'),
        )
        messages.error(request, 'Too many login attempts. Please wait a minute and try again.')
        return render(
            request, 'core/login.html',
            {'form': AuthenticationForm(), 'google_oauth_configured': settings.GOOGLE_OAUTH_CONFIGURED},
            status=429,
        )

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        login(request, user)
        messages.success(request, f'Welcome back, {user.first_name or user.username}!')
        # `next` is attacker-controlled query-string input (anyone can send a
        # login link with ?next=https://evil.example/phish). Django's own
        # LoginView guards this the same way: only follow it if it resolves to
        # this host and scheme, otherwise fall back to the normal dashboard.
        next_url = request.GET.get('next')
        if not (next_url and url_has_allowed_host_and_scheme(
            url=next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )):
            next_url = 'dashboard'
        return redirect(next_url)
    return render(request, 'core/login.html', {
        'form': form, 'google_oauth_configured': settings.GOOGLE_OAUTH_CONFIGURED,
    })


def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out successfully.')
    return redirect('landing')


# ─────────────────────────────────────────────
# GOOGLE OAUTH
# ─────────────────────────────────────────────
#
#   google_login_view            -- redirect to Google, stash CSRF `state`
#   google_callback_view         -- verify token, branch: log in / new user / link
#   google_complete_profile_view -- brand-new user picks username+password
#   google_link_confirm_view     -- existing email/password user opts in to linking
#
# 'pending_google' in the session holds the verified-but-not-yet-actioned
# Google identity between the callback and whichever follow-up view handles
# it. It is never treated as authentication by itself: it only carries
# claims Google already cryptographically verified in exchange_code_for_claims,
# and every view that reads it re-checks staleness via _pending_google_data().

GOOGLE_PENDING_SESSION_MAX_AGE = timedelta(minutes=10)


def _pending_google_data(request):
    """Reads and validates the pending Google identity stashed in the
    session by google_callback_view. Returns the stored dict, or None if
    there isn't one, it's malformed, or it's gone stale (e.g. the user sat
    on the complete-profile page too long) -- callers treat None as 'start
    the sign-in over'.
    """
    pending = request.session.get('pending_google')
    if not pending:
        return None
    try:
        stored_at = datetime.fromisoformat(pending['stored_at'])
    except (KeyError, ValueError):
        del request.session['pending_google']
        return None
    if timezone.now() - stored_at > GOOGLE_PENDING_SESSION_MAX_AGE:
        del request.session['pending_google']
        return None
    return pending


def google_login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if not settings.GOOGLE_OAUTH_CONFIGURED:
        messages.error(request, 'Google sign-in is not available right now.')
        return redirect('login')
    state = generate_state()
    request.session['google_oauth_state'] = state
    return redirect(build_authorization_url(state))


@ratelimit(key='ip', rate=settings.LOGIN_RATE_LIMIT, method='GET', block=False)
def google_callback_view(request):
    if getattr(request, 'limited', False):
        logger.warning('Google OAuth callback rate limit hit from %s', get_client_ip(request))
        messages.error(request, 'Too many attempts. Please wait a minute and try again.')
        return redirect('login')

    if not settings.GOOGLE_OAUTH_CONFIGURED:
        messages.error(request, 'Google sign-in is not available right now.')
        return redirect('login')

    if request.GET.get('error'):
        # User hit "Cancel" on Google's consent screen, or Google itself
        # refused -- not a bug, just no code to redeem.
        messages.info(request, 'Google sign-in was cancelled.')
        return redirect('login')

    expected_state = request.session.pop('google_oauth_state', None)
    received_state = request.GET.get('state')
    if not expected_state or not received_state or not secrets.compare_digest(expected_state, received_state):
        logger.warning('Google OAuth state mismatch from %s', get_client_ip(request))
        messages.error(request, 'Your Google sign-in session expired or is invalid. Please try again.')
        return redirect('login')

    code = request.GET.get('code')
    if not code:
        messages.error(request, 'Google sign-in did not complete. Please try again.')
        return redirect('login')

    try:
        claims = exchange_code_for_claims(code)
    except GoogleOAuthError as exc:
        logger.warning('Google OAuth exchange failed: %s', exc)
        messages.error(request, 'We could not verify your Google account. Please try again.')
        return redirect('login')

    if not claims.get('email_verified'):
        messages.error(
            request,
            'Your Google email is not verified. Please verify it with Google and try again.',
        )
        return redirect('login')

    google_id = claims['sub']
    email = claims['email']

    try:
        google_account = GoogleAccount.objects.select_related('user').get(google_id=google_id)
    except GoogleAccount.DoesNotExist:
        google_account = None

    if google_account is not None:
        if not google_account.user.is_active:
            messages.error(request, 'This account is disabled.')
            return redirect('login')
        login(request, google_account.user)
        messages.success(
            request,
            f'Welcome back, {google_account.user.first_name or google_account.user.username}!',
        )
        return redirect('dashboard')

    pending = {
        'google_id': google_id,
        'email': email,
        'first_name': claims.get('given_name', ''),
        'last_name': claims.get('family_name', ''),
        'stored_at': timezone.now().isoformat(),
    }

    # No GoogleAccount for this Google identity yet. User.email has no
    # unique constraint in this project, so only treat "exactly one match"
    # as safe to offer linking -- 0 matches is a brand-new user, and >1 is
    # an unresolvable ambiguity: log it and fall back to new-user rather
    # than guess which account to link.
    matches = list(User.objects.filter(email__iexact=email))
    if len(matches) == 1:
        request.session['pending_google'] = pending
        request.session['pending_google_link_user_id'] = matches[0].id
        return redirect('google_link_confirm')

    if len(matches) > 1:
        logger.warning(
            'Google sign-in for %s matches %d existing accounts by email; '
            'treating as new-user signup rather than guessing which to link.',
            email, len(matches),
        )

    request.session['pending_google'] = pending
    return redirect('google_complete_profile')


@ratelimit(key='ip', rate=settings.REGISTRATION_RATE_LIMIT, method='POST', block=False)
def google_complete_profile_view(request):
    pending = _pending_google_data(request)
    if pending is None:
        messages.error(request, 'Your Google sign-in session expired. Please start again.')
        return redirect('login')

    if request.user.is_authenticated:
        return redirect('dashboard')

    # Someone may have already finished creating this exact account (double
    # submit, two tabs) between the callback and now.
    if GoogleAccount.objects.filter(google_id=pending['google_id']).exists():
        del request.session['pending_google']
        messages.info(request, 'That Google account is already linked. Please sign in.')
        return redirect('login')

    if getattr(request, 'limited', False):
        logger.warning('Google profile-completion rate limit hit from %s', get_client_ip(request))
        messages.error(request, 'Too many attempts. Please wait a minute and try again.')
        return render(request, 'core/google_complete_profile.html', {
            'form': GoogleCompleteProfileForm(), 'email': pending['email'],
        }, status=429)

    if request.method == 'POST':
        form = GoogleCompleteProfileForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.email = pending['email']
                    user.first_name = pending['first_name']
                    user.last_name = pending['last_name']
                    user.save()
                    GoogleAccount.objects.create(
                        user=user,
                        google_id=pending['google_id'],
                        email=pending['email'],
                        email_verified=True,
                    )
            except IntegrityError:
                # A concurrent request won the race on google_id's unique
                # constraint after our pre-check above -- same identity,
                # already finished, by another tab/request.
                logger.info(
                    'Race creating GoogleAccount for %s; already created by a concurrent request.',
                    pending['email'],
                )
                del request.session['pending_google']
                messages.info(request, 'That Google account is already linked. Please sign in.')
                return redirect('login')

            del request.session['pending_google']
            login(request, user)
            messages.success(
                request, f'Welcome, {user.first_name or user.username}! Your account has been created.'
            )
            return redirect('dashboard')
    else:
        form = GoogleCompleteProfileForm()

    return render(request, 'core/google_complete_profile.html', {
        'form': form,
        'email': pending['email'],
    })


@ratelimit(key='ip', rate=settings.LOGIN_RATE_LIMIT, method='POST', block=False)
def google_link_confirm_view(request):
    pending = _pending_google_data(request)
    user_id = request.session.get('pending_google_link_user_id')
    if pending is None or not user_id:
        messages.error(request, 'Your Google sign-in session expired. Please start again.')
        return redirect('login')

    if request.user.is_authenticated:
        return redirect('dashboard')

    try:
        target_user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        del request.session['pending_google']
        del request.session['pending_google_link_user_id']
        messages.error(request, 'That account no longer exists. Please try again.')
        return redirect('login')

    if not target_user.is_active:
        messages.error(request, 'This account is disabled.')
        return redirect('login')

    if GoogleAccount.objects.filter(google_id=pending['google_id']).exists():
        del request.session['pending_google']
        del request.session['pending_google_link_user_id']
        messages.info(request, 'That Google account is already linked. Please sign in.')
        return redirect('login')

    if request.method == 'POST':
        if getattr(request, 'limited', False):
            logger.warning('Google link-confirm rate limit hit from %s', get_client_ip(request))
            messages.error(request, 'Too many attempts. Please wait a minute and try again.')
            return render(
                request, 'core/google_link_confirm.html', {'email': pending['email']}, status=429,
            )

        if 'confirm' in request.POST:
            try:
                with transaction.atomic():
                    GoogleAccount.objects.create(
                        user=target_user,
                        google_id=pending['google_id'],
                        email=pending['email'],
                        email_verified=True,
                    )
            except IntegrityError:
                logger.info(
                    'Race linking GoogleAccount for %s; already linked by a concurrent request.',
                    pending['email'],
                )
                del request.session['pending_google']
                del request.session['pending_google_link_user_id']
                messages.info(request, 'That Google account is already linked. Please sign in.')
                return redirect('login')

            del request.session['pending_google']
            del request.session['pending_google_link_user_id']
            login(request, target_user)
            messages.success(
                request,
                f'Google account linked. Welcome back, {target_user.first_name or target_user.username}!',
            )
            return redirect('dashboard')

        del request.session['pending_google']
        del request.session['pending_google_link_user_id']
        messages.info(request, 'Google sign-in was not linked. You can still log in with your password.')
        return redirect('login')

    return render(request, 'core/google_link_confirm.html', {'email': pending['email']})


# ─────────────────────────────────────────────
# AUTHENTICATED VIEWS
# ─────────────────────────────────────────────

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

    return render(request, 'core/dashboard.html', {
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

    return render(request, 'core/subject_list.html', {
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

    return render(request, 'core/chapter_list.html', {
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

    quiz = getattr(chapter, 'quiz', None)

    return render(request, 'core/lesson_detail.html', {
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
def quiz_view(request, class_slug, subject_slug, chapter_slug):
    # Scoped through class -> subject -> chapter, same as lesson_detail.
    # Chapter.slug is only unique *within* a subject (see
    # Chapter.Meta.unique_together), so looking it up by slug alone would
    # raise MultipleObjectsReturned as soon as two chapters in different
    # classes happened to share a slug.
    klass, subject = _get_subject(class_slug, subject_slug)
    chapter = get_object_or_404(Chapter, subject=subject, slug=chapter_slug)
    quiz = get_object_or_404(Quiz, chapter=chapter)
    # Materialized once: `questions.count()` on an unevaluated queryset would
    # otherwise issue its own SELECT COUNT(*) instead of reusing the rows
    # prefetch_related just fetched.
    questions = list(quiz.questions.prefetch_related('choices').all())

    if request.method == 'POST':
        score = 0
        total = len(questions)
        results = []

        for question in questions:
            # `.all()` reads from the prefetch cache above; `.filter()`/`.get()`
            # on the related manager would each re-hit the database, silently
            # defeating the prefetch_related for every question in the quiz.
            choices = list(question.choices.all())
            selected_id = request.POST.get(f'question_{question.id}')
            correct_choice = next((c for c in choices if c.is_correct), None)
            selected_choice = None
            is_correct = False

            if selected_id:
                try:
                    selected_id = int(selected_id)
                except ValueError:
                    selected_id = None
                if selected_id is not None:
                    selected_choice = next((c for c in choices if c.id == selected_id), None)
                    if selected_choice is not None:
                        is_correct = selected_choice.is_correct
                        if is_correct:
                            score += 1

            results.append({
                'question': question,
                'selected': selected_choice,
                'correct': correct_choice,
                'is_correct': is_correct,
            })

        passed = (score / total * 100) >= quiz.pass_percentage if total > 0 else False
        attempt = QuizAttempt.objects.create(
            user=request.user, quiz=quiz,
            score=score, total=total, passed=passed
        )

        return render(request, 'core/quiz_result.html', {
            'quiz': quiz,
            'results': results,
            'attempt': attempt,
        })

    return render(request, 'core/quiz.html', {
        'quiz': quiz,
        'questions': questions,
        'chapter': chapter,
        'subject': subject,
        'klass': klass,
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

    return render(request, 'core/search_results.html', {
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
