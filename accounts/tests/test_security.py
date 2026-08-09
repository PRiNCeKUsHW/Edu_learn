"""Security-boundary test: the open-redirect fix on login's `next` param."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


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
