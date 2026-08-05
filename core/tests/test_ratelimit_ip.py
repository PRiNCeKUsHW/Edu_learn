"""core.ratelimit.get_client_ip — the fix for the rate limiter treating
every visitor behind a reverse proxy as one shared IP (see the module's
own docstring for the full reasoning). Split from test_auth.py: this is
about the extraction function itself, not the views that use it.
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.http import HttpRequest
from django.test import TestCase
from django.urls import reverse
from django_ratelimit.core import _split_rate
from freezegun import freeze_time

from core.ratelimit import get_client_ip


class GetClientIpTests(TestCase):
    """Unit-level: proves the extraction logic itself is correct,
    independent of whatever Railway's proxy actually does at runtime —
    that part isn't something a test on this machine can verify."""

    def _request(self, **meta):
        request = HttpRequest()
        request.META.update(meta)
        return request

    def test_uses_x_real_ip_when_present(self):
        request = self._request(HTTP_X_REAL_IP='203.0.113.10', REMOTE_ADDR='10.0.0.5')
        self.assertEqual(get_client_ip(request), '203.0.113.10')

    def test_strips_whitespace_from_x_real_ip(self):
        request = self._request(HTTP_X_REAL_IP='  203.0.113.10  ')
        self.assertEqual(get_client_ip(request), '203.0.113.10')

    def test_falls_back_to_remote_addr_when_header_absent(self):
        request = self._request(REMOTE_ADDR='10.0.0.5')
        self.assertEqual(get_client_ip(request), '10.0.0.5')

    def test_falls_back_to_remote_addr_when_header_is_empty_string(self):
        request = self._request(HTTP_X_REAL_IP='', REMOTE_ADDR='10.0.0.5')
        self.assertEqual(get_client_ip(request), '10.0.0.5')

    def test_returns_empty_string_when_neither_is_set(self):
        request = self._request()
        self.assertEqual(get_client_ip(request), '')


class RateLimitProxyDifferentiationTests(TestCase):
    """End-to-end: the actual scenario from the audit. Two different real
    visitors behind the same reverse proxy share one REMOTE_ADDR (Django's
    test client always sets REMOTE_ADDR='127.0.0.1', standing in for
    "the proxy's IP" here) but arrive with different X-Real-IP — proving
    the fix keeps them in independent rate-limit buckets instead of one
    shared one."""

    def setUp(self):
        cache.clear()
        User.objects.create_user(username='student', password='pass12345')

    @freeze_time('2026-01-01 12:00:00')
    def test_one_visitor_being_rate_limited_does_not_affect_another(self):
        limit, _ = _split_rate(settings.LOGIN_RATE_LIMIT)
        for _ in range(limit):
            response = self.client.post(
                reverse('login'), {'username': 'student', 'password': 'wrong-password'},
                HTTP_X_REAL_IP='203.0.113.10',
            )
            self.assertEqual(response.status_code, 200)

        limited = self.client.post(
            reverse('login'), {'username': 'student', 'password': 'wrong-password'},
            HTTP_X_REAL_IP='203.0.113.10',
        )
        self.assertEqual(limited.status_code, 429)

        # A different visitor, same REMOTE_ADDR (same simulated proxy),
        # different X-Real-IP -- must be completely unaffected.
        other_visitor = self.client.post(
            reverse('login'), {'username': 'student', 'password': 'wrong-password'},
            HTTP_X_REAL_IP='203.0.113.20',
        )
        self.assertEqual(other_visitor.status_code, 200)
