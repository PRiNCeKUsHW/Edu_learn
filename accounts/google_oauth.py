"""Google OAuth 2.0 mechanics: building the authorization URL, exchanging
an authorization code for tokens, and verifying the returned ID token.

Kept separate from views.py so the network/crypto logic is independently
testable (mocked in tests) without needing to exercise the full view,
session, and branching logic every time — and so views.py stays focused on
what to *do* with a verified identity, not how to get one.

Uses the plain server-side "authorization code" flow (a browser redirect to
Google and back), not Google's client-side "Sign In With Google" JS widget:
GOOGLE_OAUTH_CLIENT_SECRET never reaches the browser, and every check
(state, signature, audience, expiry, issuer, email_verified) happens here,
on the server — nothing about the caller's own claims about itself is ever
trusted.
"""
import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings
from google.auth import exceptions as google_exceptions
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

AUTHORIZATION_ENDPOINT = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'

# openid+email+profile is the minimum needed to identify the visitor and
# show their name — no Calendar/Drive/etc scopes, since nothing here ever
# calls another Google API on the user's behalf after sign-in.
SCOPES = 'openid email profile'

# Timeouts on every outbound call: this runs inside a request-response
# cycle, so a hung connection to Google must not hang the whole worker.
REQUEST_TIMEOUT_SECONDS = 10


class GoogleOAuthError(Exception):
    """Any failure in the exchange/verify pipeline — bad code, network
    failure, invalid signature, expired token, wrong audience/issuer.
    Views catch this once and show a single friendly message rather than
    needing to know about requests.RequestException / ValueError /
    GoogleAuthError / a malformed response individually.

    Deliberately does *not* cover "the email isn't verified" — that's a
    successfully-verified, authentic token that this app chooses not to
    trust for a different (policy) reason, not a verification failure, so
    the caller checks the `email_verified` claim itself on a clean result.
    """


def generate_state():
    """An unguessable, single-use token for the OAuth `state` parameter —
    the mechanism that stops a third party from tricking a victim into
    completing an OAuth flow *the attacker* initiated (a CSRF against the
    login flow itself, distinct from Django's own CSRF token, which doesn't
    apply to a GET-based redirect)."""
    return secrets.token_urlsafe(32)


def build_authorization_url(state):
    """The URL to send the browser to. `state` must already be stored in
    the session by the caller — this function only builds the URL."""
    params = {
        'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
        'redirect_uri': settings.GOOGLE_OAUTH_REDIRECT_URI,
        'response_type': 'code',
        'scope': SCOPES,
        'state': state,
        # No refresh token requested — nothing here calls a Google API on
        # the user's behalf after sign-in, so there's nothing to refresh.
        'access_type': 'online',
        # Always show the account chooser rather than silently reusing
        # whichever Google account happens to be active in the browser.
        'prompt': 'select_account',
    }
    return f'{AUTHORIZATION_ENDPOINT}?{urlencode(params)}'


def exchange_code_for_claims(code):
    """Server-to-server: trades the authorization `code` for tokens, then
    cryptographically verifies the ID token before returning its claims.

    This is the only place GOOGLE_OAUTH_CLIENT_SECRET is used, and it never
    leaves this function. Raises GoogleOAuthError on any failure; callers
    don't need to know *how* it failed, only that the identity in hand
    can't be trusted.
    """
    try:
        response = requests.post(
            TOKEN_ENDPOINT,
            data={
                'code': code,
                'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
                'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
                'redirect_uri': settings.GOOGLE_OAUTH_REDIRECT_URI,
                'grant_type': 'authorization_code',
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise GoogleOAuthError('Could not reach Google.') from exc

    if response.status_code != 200:
        # A used/expired/forged code, a redirect_uri mismatch, etc. — Google
        # rejects the exchange outright rather than returning tokens.
        raise GoogleOAuthError(
            f'Google rejected the authorization code (HTTP {response.status_code}).'
        )

    try:
        raw_id_token = response.json()['id_token']
    except (ValueError, KeyError) as exc:
        raise GoogleOAuthError('Google did not return a usable ID token.') from exc

    try:
        # Verifies the signature against Google's own public keys, and that
        # the token is unexpired, issued by Google, and issued *for this
        # app* specifically (audience=our client ID) — a token minted for a
        # different app can't be replayed against this one.
        claims = google_id_token.verify_oauth2_token(
            raw_id_token,
            google_requests.Request(),
            audience=settings.GOOGLE_OAUTH_CLIENT_ID,
        )
    except (ValueError, google_exceptions.GoogleAuthError) as exc:
        raise GoogleOAuthError('Could not verify the Google ID token.') from exc

    return claims
