"""Google OAuth sign-in/sign-up: the redirect-to-Google entry point, the
callback's verify-and-branch logic, and the two follow-up flows (new-user
profile completion, existing-user link confirmation).

Network calls to Google are never made here — exchange_code_for_claims
(core.views.exchange_code_for_claims, imported from core.google_oauth) is
mocked at the view layer for every test that exercises the callback, so
these tests are about *this app's* branching/session/security logic, not
Google's API. core/tests/test_google_oauth_mechanics.py-equivalent coverage
of the token exchange itself (network/verification translation into
GoogleOAuthError) lives in GoogleOAuthMechanicsTests below, with `requests`
and `google.oauth2.id_token` mocked directly.

Every test that reaches past the "is Google OAuth configured" gate uses
@override_settings to set GOOGLE_OAUTH_CONFIGURED=True — it's a value
derived once at settings-module import time (see settings.py), so
overriding the three underlying config() values alone would not update it;
it must be overridden explicitly alongside them.
"""
from unittest.mock import patch

import requests
from django.contrib.auth.models import User
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django_ratelimit.core import _split_rate
from freezegun import freeze_time

from core.google_oauth import GoogleOAuthError, exchange_code_for_claims
from core.models import GoogleAccount

GOOGLE_OAUTH_TEST_SETTINGS = dict(
    GOOGLE_OAUTH_CLIENT_ID='test-client-id.apps.googleusercontent.com',
    GOOGLE_OAUTH_CLIENT_SECRET='test-client-secret',
    GOOGLE_OAUTH_REDIRECT_URI='http://testserver/accounts/google/callback/',
    GOOGLE_OAUTH_CONFIGURED=True,
)


def make_claims(google_id='google-uid-1', email='newuser@example.com',
                 email_verified=True, given_name='New', family_name='User'):
    return {
        'sub': google_id,
        'email': email,
        'email_verified': email_verified,
        'given_name': given_name,
        'family_name': family_name,
    }


class GoogleOAuthMechanicsTests(TestCase):
    """Unit tests for core/google_oauth.py's exchange_code_for_claims, with
    the network call and the cryptographic verification both mocked — these
    exercise the *translation* of every failure mode into GoogleOAuthError,
    not Google's actual behaviour."""

    @patch('core.google_oauth.google_id_token.verify_oauth2_token')
    @patch('core.google_oauth.requests.post')
    def test_successful_exchange_returns_verified_claims(self, mock_post, mock_verify):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'id_token': 'raw-jwt'}
        mock_verify.return_value = make_claims()

        claims = exchange_code_for_claims('valid-code')

        self.assertEqual(claims['email'], 'newuser@example.com')
        mock_verify.assert_called_once()

    @patch('core.google_oauth.requests.post')
    def test_network_failure_raises_google_oauth_error(self, mock_post):
        mock_post.side_effect = requests.ConnectionError('no route')
        with self.assertRaises(GoogleOAuthError):
            exchange_code_for_claims('any-code')

    @patch('core.google_oauth.requests.post')
    def test_non_200_token_response_raises_google_oauth_error(self, mock_post):
        mock_post.return_value.status_code = 400
        with self.assertRaises(GoogleOAuthError):
            exchange_code_for_claims('reused-or-expired-code')

    @patch('core.google_oauth.requests.post')
    def test_missing_id_token_in_response_raises_google_oauth_error(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'access_token': 'no-id-token-here'}
        with self.assertRaises(GoogleOAuthError):
            exchange_code_for_claims('some-code')

    @patch('core.google_oauth.google_id_token.verify_oauth2_token')
    @patch('core.google_oauth.requests.post')
    def test_expired_or_invalid_token_raises_google_oauth_error(self, mock_post, mock_verify):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {'id_token': 'expired-jwt'}
        mock_verify.side_effect = ValueError('Token expired')
        with self.assertRaises(GoogleOAuthError):
            exchange_code_for_claims('some-code')


class GoogleLoginViewTests(TestCase):
    @override_settings(GOOGLE_OAUTH_CONFIGURED=False)
    def test_redirects_to_login_when_not_configured(self):
        # Explicitly forced False rather than relying on the ambient
        # default: a developer's local .env may have real credentials set
        # (e.g. for manual browser testing), which would otherwise make
        # settings.GOOGLE_OAUTH_CONFIGURED True even without this override.
        response = self.client.get(reverse('google_login'))
        self.assertRedirects(response, reverse('login'))

    @override_settings(**GOOGLE_OAUTH_TEST_SETTINGS)
    def test_redirects_to_google_and_stores_csrf_state(self):
        response = self.client.get(reverse('google_login'))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('https://accounts.google.com/o/oauth2/v2/auth'))
        self.assertIn('client_id=test-client-id', response.url)
        self.assertIn('state=', response.url)
        self.assertIn('google_oauth_state', self.client.session)

    @override_settings(**GOOGLE_OAUTH_TEST_SETTINGS)
    def test_already_authenticated_user_is_redirected_to_dashboard(self):
        user = User.objects.create_user(username='stu', password='pass12345')
        self.client.force_login(user)
        response = self.client.get(reverse('google_login'))
        self.assertRedirects(response, reverse('dashboard'))


@override_settings(**GOOGLE_OAUTH_TEST_SETTINGS)
class GoogleCallbackViewTests(TestCase):
    def setUp(self):
        cache.clear()

    def _start(self):
        """Hits google_login first so the session carries the real `state`
        the callback expects — mirrors what a real browser round trip does."""
        self.client.get(reverse('google_login'))
        return self.client.session['google_oauth_state']

    def test_not_configured_redirects_to_login(self):
        with override_settings(GOOGLE_OAUTH_CONFIGURED=False):
            response = self.client.get(reverse('google_callback'), {'state': 'x', 'code': 'y'})
        self.assertRedirects(response, reverse('login'))

    def test_user_cancelling_on_google_redirects_to_login(self):
        state = self._start()
        response = self.client.get(reverse('google_callback'), {'state': state, 'error': 'access_denied'})
        self.assertRedirects(response, reverse('login'))

    def test_missing_state_is_rejected(self):
        response = self.client.get(reverse('google_callback'), {'code': 'abc'})
        self.assertRedirects(response, reverse('login'))

    def test_state_mismatch_is_rejected(self):
        self._start()
        with self.assertLogs('core.views', level='WARNING'):
            response = self.client.get(reverse('google_callback'), {'state': 'not-the-real-state', 'code': 'abc'})
        self.assertRedirects(response, reverse('login'))

    def test_state_is_single_use(self):
        state = self._start()
        with patch('core.views.exchange_code_for_claims', return_value=make_claims()):
            self.client.get(reverse('google_callback'), {'state': state, 'code': 'abc'})
        # Replaying the same (now-consumed) state must fail, not succeed again.
        with self.assertLogs('core.views', level='WARNING'):
            replay = self.client.get(reverse('google_callback'), {'state': state, 'code': 'abc'})
        self.assertRedirects(replay, reverse('login'))

    def test_missing_code_is_rejected(self):
        state = self._start()
        response = self.client.get(reverse('google_callback'), {'state': state})
        self.assertRedirects(response, reverse('login'))

    def test_invalid_or_expired_token_shows_friendly_error(self):
        state = self._start()
        with patch('core.views.exchange_code_for_claims', side_effect=GoogleOAuthError('bad token')):
            with self.assertLogs('core.views', level='WARNING'):
                response = self.client.get(reverse('google_callback'), {'state': state, 'code': 'abc'})
        self.assertRedirects(response, reverse('login'))

    def test_unverified_email_is_rejected(self):
        state = self._start()
        claims = make_claims(email_verified=False)
        with patch('core.views.exchange_code_for_claims', return_value=claims):
            response = self.client.get(reverse('google_callback'), {'state': state, 'code': 'abc'})
        self.assertRedirects(response, reverse('login'))
        self.assertFalse(User.objects.filter(email=claims['email']).exists())

    def test_brand_new_email_starts_complete_profile_flow(self):
        state = self._start()
        claims = make_claims(email='fresh@example.com')
        with patch('core.views.exchange_code_for_claims', return_value=claims):
            response = self.client.get(reverse('google_callback'), {'state': state, 'code': 'abc'})
        self.assertRedirects(response, reverse('google_complete_profile'))
        pending = self.client.session['pending_google']
        self.assertEqual(pending['google_id'], claims['sub'])
        self.assertEqual(pending['email'], 'fresh@example.com')

    def test_already_linked_google_account_logs_in_immediately(self):
        user = User.objects.create_user(username='linked', password='pass12345', email='linked@example.com')
        GoogleAccount.objects.create(user=user, google_id='existing-uid', email='linked@example.com')
        state = self._start()
        claims = make_claims(google_id='existing-uid', email='linked@example.com')
        with patch('core.views.exchange_code_for_claims', return_value=claims):
            response = self.client.get(reverse('google_callback'), {'state': state, 'code': 'abc'})
        self.assertRedirects(response, reverse('dashboard'))
        dash = self.client.get(reverse('dashboard'))
        self.assertEqual(dash.status_code, 200)

    def test_disabled_linked_account_cannot_log_in(self):
        user = User.objects.create_user(username='disabled', password='pass12345', is_active=False)
        GoogleAccount.objects.create(user=user, google_id='disabled-uid', email='disabled@example.com')
        state = self._start()
        claims = make_claims(google_id='disabled-uid', email='disabled@example.com')
        with patch('core.views.exchange_code_for_claims', return_value=claims):
            response = self.client.get(reverse('google_callback'), {'state': state, 'code': 'abc'})
        self.assertRedirects(response, reverse('login'))
        dash = self.client.get(reverse('dashboard'))
        self.assertEqual(dash.status_code, 302)

    def test_existing_password_account_with_matching_email_starts_link_flow(self):
        User.objects.create_user(username='haspassword', password='pass12345', email='shared@example.com')
        state = self._start()
        claims = make_claims(google_id='new-uid', email='shared@example.com')
        with patch('core.views.exchange_code_for_claims', return_value=claims):
            response = self.client.get(reverse('google_callback'), {'state': state, 'code': 'abc'})
        self.assertRedirects(response, reverse('google_link_confirm'))
        self.assertEqual(self.client.session['pending_google']['email'], 'shared@example.com')

    def test_ambiguous_email_match_falls_back_to_new_user_flow(self):
        # User.email has no unique constraint in this project — two accounts
        # can share an email. Linking to either would be a guess, so the
        # callback must treat this the same as "no match" rather than pick one.
        User.objects.create_user(username='dup1', password='pass12345', email='dup@example.com')
        User.objects.create_user(username='dup2', password='pass12345', email='dup@example.com')
        state = self._start()
        claims = make_claims(google_id='new-uid', email='dup@example.com')
        with patch('core.views.exchange_code_for_claims', return_value=claims):
            with self.assertLogs('core.views', level='WARNING'):
                response = self.client.get(reverse('google_callback'), {'state': state, 'code': 'abc'})
        self.assertRedirects(response, reverse('google_complete_profile'))

    @freeze_time('2026-01-01 12:00:00')
    def test_callback_rate_limited_after_configured_attempts_per_window(self):
        limit, _ = _split_rate(settings.LOGIN_RATE_LIMIT)
        for _ in range(limit):
            self.client.get(reverse('google_callback'), {'state': 'x', 'code': 'y'})
        with self.assertLogs('core.views', level='WARNING') as logs:
            limited = self.client.get(reverse('google_callback'), {'state': 'x', 'code': 'y'})
        self.assertRedirects(limited, reverse('login'))
        self.assertTrue(any('Google OAuth callback rate limit hit' in m for m in logs.output))


@override_settings(**GOOGLE_OAUTH_TEST_SETTINGS)
class GoogleCompleteProfileViewTests(TestCase):
    def setUp(self):
        cache.clear()

    def _set_pending(self, **overrides):
        pending = {
            'google_id': 'new-uid', 'email': 'fresh@example.com',
            'first_name': 'Fresh', 'last_name': 'User',
            'stored_at': timezone.now().isoformat(),
        }
        pending.update(overrides)
        session = self.client.session
        session['pending_google'] = pending
        session.save()
        return pending

    def test_no_pending_session_redirects_to_login(self):
        response = self.client.get(reverse('google_complete_profile'))
        self.assertRedirects(response, reverse('login'))

    def test_stale_pending_session_is_rejected(self):
        with freeze_time('2026-01-01 12:00:00'):
            self._set_pending()
        with freeze_time('2026-01-01 12:11:00'):  # past the 10-minute window
            response = self.client.get(reverse('google_complete_profile'))
        self.assertRedirects(response, reverse('login'))

    def test_get_renders_form_with_googles_email(self):
        self._set_pending(email='fresh@example.com')
        response = self.client.get(reverse('google_complete_profile'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'fresh@example.com')

    def test_valid_submission_creates_account_links_google_and_logs_in(self):
        self._set_pending(email='fresh@example.com', first_name='Fresh', last_name='User')
        response = self.client.post(reverse('google_complete_profile'), {
            'username': 'freshuser', 'password1': 'a-strong-passw0rd', 'password2': 'a-strong-passw0rd',
        })
        self.assertRedirects(response, reverse('dashboard'))

        user = User.objects.get(username='freshuser')
        self.assertEqual(user.email, 'fresh@example.com')
        self.assertEqual(user.first_name, 'Fresh')
        google_account = GoogleAccount.objects.get(user=user)
        self.assertEqual(google_account.google_id, 'new-uid')
        self.assertTrue(google_account.email_verified)

        dash = self.client.get(reverse('dashboard'))
        self.assertEqual(dash.status_code, 200)
        self.assertNotIn('pending_google', self.client.session)

    def test_mismatched_passwords_are_rejected_without_creating_account(self):
        self._set_pending()
        response = self.client.post(reverse('google_complete_profile'), {
            'username': 'freshuser', 'password1': 'a-strong-passw0rd', 'password2': 'different',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='freshuser').exists())

    def test_username_collision_is_rejected(self):
        User.objects.create_user(username='taken', password='pass12345')
        self._set_pending()
        response = self.client.post(reverse('google_complete_profile'), {
            'username': 'taken', 'password1': 'a-strong-passw0rd', 'password2': 'a-strong-passw0rd',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(username='taken').count(), 1)

    def test_already_authenticated_user_is_redirected_to_dashboard(self):
        user = User.objects.create_user(username='already', password='pass12345')
        self.client.force_login(user)
        self._set_pending()
        response = self.client.get(reverse('google_complete_profile'))
        self.assertRedirects(response, reverse('dashboard'))

    def test_concurrent_completion_of_same_google_identity_is_handled_gracefully(self):
        # Simulates a double-submit / two-tabs race: another request already
        # created the GoogleAccount for this google_id between page-load and
        # this submission.
        other_user = User.objects.create_user(username='winner', password='pass12345')
        GoogleAccount.objects.create(user=other_user, google_id='new-uid', email='fresh@example.com')
        self._set_pending()
        response = self.client.post(reverse('google_complete_profile'), {
            'username': 'loser', 'password1': 'a-strong-passw0rd', 'password2': 'a-strong-passw0rd',
        })
        self.assertRedirects(response, reverse('login'))
        self.assertFalse(User.objects.filter(username='loser').exists())

    @freeze_time('2026-01-01 12:00:00')
    def test_rate_limited_after_configured_attempts_per_window(self):
        limit, _ = _split_rate(settings.REGISTRATION_RATE_LIMIT)
        self._set_pending()
        for i in range(limit):
            self.client.post(reverse('google_complete_profile'), {
                'username': f'ratecheck{i}', 'password1': 'x', 'password2': 'x',
            })
        with self.assertLogs('core.views', level='WARNING') as logs:
            limited = self.client.post(reverse('google_complete_profile'), {
                'username': 'onemore', 'password1': 'a-strong-passw0rd', 'password2': 'a-strong-passw0rd',
            })
        self.assertEqual(limited.status_code, 429)
        self.assertFalse(User.objects.filter(username='onemore').exists())
        self.assertTrue(any('Google profile-completion rate limit hit' in m for m in logs.output))


@override_settings(**GOOGLE_OAUTH_TEST_SETTINGS)
class GoogleLinkConfirmViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.existing_user = User.objects.create_user(
            username='haspassword', password='pass12345', email='shared@example.com',
        )

    def _set_pending(self, user=None, **overrides):
        pending = {
            'google_id': 'new-uid', 'email': 'shared@example.com',
            'first_name': 'Shared', 'last_name': 'User',
            'stored_at': timezone.now().isoformat(),
        }
        pending.update(overrides)
        session = self.client.session
        session['pending_google'] = pending
        session['pending_google_link_user_id'] = (user or self.existing_user).id
        session.save()
        return pending

    def test_no_pending_session_redirects_to_login(self):
        response = self.client.get(reverse('google_link_confirm'))
        self.assertRedirects(response, reverse('login'))

    def test_get_renders_confirmation_with_googles_email(self):
        self._set_pending()
        response = self.client.get(reverse('google_link_confirm'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'shared@example.com')

    def test_confirming_links_google_account_and_logs_in(self):
        self._set_pending()
        response = self.client.post(reverse('google_link_confirm'), {'confirm': '1'})
        self.assertRedirects(response, reverse('dashboard'))

        google_account = GoogleAccount.objects.get(user=self.existing_user)
        self.assertEqual(google_account.google_id, 'new-uid')

        dash = self.client.get(reverse('dashboard'))
        self.assertEqual(dash.status_code, 200)
        self.assertNotIn('pending_google', self.client.session)

    def test_declining_does_not_link_and_password_login_still_works(self):
        self._set_pending()
        response = self.client.post(reverse('google_link_confirm'), {})
        self.assertRedirects(response, reverse('login'))
        self.assertFalse(GoogleAccount.objects.filter(user=self.existing_user).exists())

        # Declining the link must not break the account's normal password login.
        login_response = self.client.post(reverse('login'), {
            'username': 'haspassword', 'password': 'pass12345',
        })
        self.assertRedirects(login_response, reverse('dashboard'))

    def test_disabled_target_account_cannot_be_linked(self):
        self.existing_user.is_active = False
        self.existing_user.save()
        self._set_pending()
        response = self.client.post(reverse('google_link_confirm'), {'confirm': '1'})
        self.assertRedirects(response, reverse('login'))
        self.assertFalse(GoogleAccount.objects.filter(user=self.existing_user).exists())

    def test_concurrent_linking_of_same_google_identity_is_handled_gracefully(self):
        other_user = User.objects.create_user(username='other', password='pass12345')
        GoogleAccount.objects.create(user=other_user, google_id='new-uid', email='shared@example.com')
        self._set_pending()
        response = self.client.post(reverse('google_link_confirm'), {'confirm': '1'})
        self.assertRedirects(response, reverse('login'))
        self.assertFalse(GoogleAccount.objects.filter(user=self.existing_user).exists())

    @freeze_time('2026-01-01 12:00:00')
    def test_rate_limited_after_configured_attempts_per_window(self):
        limit, _ = _split_rate(settings.LOGIN_RATE_LIMIT)
        self._set_pending()
        for _ in range(limit):
            self.client.post(reverse('google_link_confirm'), {})
            self._set_pending()  # each decline clears the session; reset for the next attempt
        with self.assertLogs('core.views', level='WARNING') as logs:
            limited = self.client.post(reverse('google_link_confirm'), {'confirm': '1'})
        self.assertEqual(limited.status_code, 429)
        self.assertFalse(GoogleAccount.objects.filter(user=self.existing_user).exists())
        self.assertTrue(any('Google link-confirm rate limit hit' in m for m in logs.output))


class RegressionTests(TestCase):
    """Confirms the Google OAuth feature doesn't disturb ordinary
    email/password login for accounts that already have a password
    (created directly, or via the Google complete-profile flow) --
    signup itself is Google-only by design, covered in test_auth.py's
    RegistrationTests."""

    def setUp(self):
        cache.clear()

    def test_password_login_unaffected_by_google_oauth_feature(self):
        User.objects.create_user(username='plain', password='pass12345')
        response = self.client.post(reverse('login'), {
            'username': 'plain', 'password': 'pass12345',
        })
        self.assertRedirects(response, reverse('dashboard'))
