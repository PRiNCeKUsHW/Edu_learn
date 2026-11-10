"""Client-IP extraction for django-ratelimit, referenced from settings.py
via RATELIMIT_IP_META_KEY. Its own module (not inline in settings.py) so
the extraction logic stays independently testable.
"""


def get_client_ip(request):
    """The real visitor's IP behind Railway's edge proxy — never
    REMOTE_ADDR alone, which behind any reverse proxy is the proxy's own
    IP, collapsing every visitor into one shared rate-limit bucket (the
    exact bug this exists to fix: 5 failed logins from anyone would rate
    limit login for everyone).

    Railway's own support has genuinely conflicting guidance on whether
    X-Forwarded-For is safe to trust directly: one Railway staff reply says
    client-supplied values are stripped at the edge; another report says
    they're appended, i.e. NOT stripped — which would make the header
    trivially spoofable (a client sets any X-Forwarded-For value they like
    on the very first hop, choosing their own rate-limit bucket at will).

    X-Real-IP is what Railway frames as the dedicated, non-ambiguous
    answer, so it's used here instead, with one documented, tracked
    caveat: when traffic passes through Railway's CDN/custom-domain layer,
    X-Real-IP can reflect the CDN edge's own IP rather than the visitor's.
    That failure mode degrades to the *original* bug (several real users
    briefly sharing one bucket) rather than a security bypass (an attacker
    choosing their own bucket) — the safer of the two ways this can go
    wrong, and why it's the default here rather than X-Forwarded-For.

    Falls back to REMOTE_ADDR for local development, where there's no
    proxy in front of the app and neither header is ever set — this is
    also what makes the existing rate-limit tests keep working unchanged,
    since Django's test client sets REMOTE_ADDR but not X-Real-IP.
    """
    real_ip = request.META.get('HTTP_X_REAL_IP', '')
    if real_ip:
        return real_ip.strip()
    return request.META.get('REMOTE_ADDR', '')


def rate_limited_admin_login(login_view):
    """Wraps Django admin's login view with the same per-IP attempt limit as
    the site's own login page (settings.LOGIN_RATE_LIMIT), counted in its own
    bucket. Only POSTs count, so opening the page is never limited.

    Applied in elearn_project/urls.py. A plain-text 429 rather than a styled
    page: only staff ever reach this screen, and only by hammering it.
    """
    # Imported here, not at module top: settings.py names this module in
    # RATELIMIT_IP_META_KEY, and get_client_ip above must stay importable
    # without pulling in anything that itself reads settings at import time.
    import logging

    from django.conf import settings
    from django.http import HttpResponse
    from django_ratelimit.decorators import ratelimit

    logger = logging.getLogger(__name__)

    @ratelimit(
        key='ip', rate=settings.LOGIN_RATE_LIMIT, method='POST',
        group='admin_login', block=False,
    )
    def limited_login(request, *args, **kwargs):
        if getattr(request, 'limited', False):
            # The typed username is deliberately not logged: it is free text
            # of any length, and people do paste a password into that box.
            logger.warning('Admin login rate limit hit from %s', get_client_ip(request))
            return HttpResponse(
                'Too many login attempts. Please wait a minute and try again.',
                status=429, content_type='text/plain',
            )
        return login_view(request, *args, **kwargs)

    return limited_login
