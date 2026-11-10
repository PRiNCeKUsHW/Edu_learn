"""Security-boundary test: the open-redirect fix on login's `next` param."""
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from freezegun import freeze_time


class LoginRedirectSecurityTests(TestCase):
    """`next` is attacker-controlled query-string input and must never send
    a user off-site after a successful login."""

    def setUp(self):
        self.user = User.objects.create_user(username='student', password='pass12345')

    def test_external_next_url_is_ignored(self):
        url = reverse('login') + '?next=https://evil.example/phish'
        response = self.client.post(url, {'username': 'student', 'password': 'pass12345'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard'))

    def test_protocol_relative_next_url_is_ignored(self):
        """`//evil.example/` has no scheme, but browsers treat it as
        off-host — a common bypass for naive `startswith('http')` checks."""
        url = reverse('login') + '?next=//evil.example/'
        response = self.client.post(url, {'username': 'student', 'password': 'pass12345'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard'))

    def test_same_host_next_url_is_honoured(self):
        target = reverse('dashboard')
        url = reverse('login') + f'?next={target}'
        response = self.client.post(url, {'username': 'student', 'password': 'pass12345'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, target)


class AdminLoginRateLimitTests(TestCase):
    """/admin/login/ is a second password door (and where /panel/ redirects
    anonymous visitors), so it carries the same attempt limit as /login/."""

    def setUp(self):
        cache.clear()
        self.url = reverse('admin:login')

    @freeze_time('2026-01-01 12:00:00')
    def test_post_is_blocked_after_the_login_rate_limit(self):
        limit = int(settings.LOGIN_RATE_LIMIT.split('/')[0])
        for _ in range(limit):
            response = self.client.post(self.url, {'username': 'nobody', 'password': 'wrong'})
            self.assertEqual(response.status_code, 200)
        response = self.client.post(self.url, {'username': 'nobody', 'password': 'wrong'})
        self.assertEqual(response.status_code, 429)

    @freeze_time('2026-01-01 12:00:00')
    def test_opening_the_page_is_never_limited(self):
        limit = int(settings.LOGIN_RATE_LIMIT.split('/')[0])
        for _ in range(limit + 5):
            self.assertEqual(self.client.get(self.url).status_code, 200)
