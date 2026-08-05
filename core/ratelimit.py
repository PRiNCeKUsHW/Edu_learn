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
