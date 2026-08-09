import logging
import secrets
from datetime import datetime, timedelta

from django.shortcuts import render, redirect
from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.views import PasswordChangeView
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django_ratelimit.decorators import ratelimit

from .forms import GoogleCompleteProfileForm, ProfileForm
from .google_oauth import (
    GoogleOAuthError, build_authorization_url, exchange_code_for_claims, generate_state,
)
from .models import GoogleAccount
from .ratelimit import get_client_ip

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# PUBLIC VIEWS
# ─────────────────────────────────────────────

def landing(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'accounts/landing.html')


# New accounts are created through Google only (see google_complete_profile_view)
# -- there is deliberately no username/email/password form or POST handler
# here anymore. Signup abuse is bounded on the Google side instead: by
# REGISTRATION_RATE_LIMIT on google_complete_profile_view, the actual
# account-creation endpoint.
def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'accounts/register.html', {
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
            request, 'accounts/login.html',
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
    return render(request, 'accounts/login.html', {
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
        return render(request, 'accounts/google_complete_profile.html', {
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

    return render(request, 'accounts/google_complete_profile.html', {
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
                request, 'accounts/google_link_confirm.html', {'email': pending['email']}, status=429,
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

    return render(request, 'accounts/google_link_confirm.html', {'email': pending['email']})


# ─────────────────────────────────────────────
# ACCOUNT SETTINGS
# ─────────────────────────────────────────────

@login_required
def account_settings_view(request):
    if request.method == 'POST':
        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated.')
            return redirect('account_settings')
    else:
        form = ProfileForm(instance=request.user)
    return render(request, 'accounts/account_settings.html', {'form': form})


class AccountPasswordChangeView(PasswordChangeView):
    """Thin wrapper around Django's own PasswordChangeView -- it already
    validates the old password, enforces AUTH_PASSWORD_VALIDATORS, and calls
    update_session_auth_hash so the session survives the change. Only the
    template and success destination are project-specific; the actual
    password-handling logic is Django's, not reinvented here.
    """
    template_name = 'accounts/account_password_change.html'
    success_url = reverse_lazy('account_settings')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Your password has been changed.')
        return response


@login_required
def account_delete_view(request):
    """Deletes the requesting user's own account. Requires re-entering the
    current password -- protects against deleting an account from an
    unattended, already-logged-in session (a shared/public computer, for
    instance), not just a stray misclick.

    GoogleAccount, Comment, QuizAttempt and LessonProgress all have
    on_delete=models.CASCADE on their `user` FK, so User.delete() already
    cleans up every related row across accounts/discussions/quizzes/progress
    -- no extra signal handling needed here.
    """
    if request.method == 'POST':
        password = request.POST.get('password', '')
        if request.user.check_password(password):
            user = request.user
            logout(request)
            user.delete()
            messages.success(request, 'Your account has been deleted.')
            return redirect('landing')
        messages.error(request, 'Incorrect password. Your account was not deleted.')
    return render(request, 'accounts/account_delete.html')
