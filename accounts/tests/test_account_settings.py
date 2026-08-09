"""Self-service account management: editing your own profile, changing your
own password, and deleting your own account.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import GoogleAccount
from curriculum.tests.factories import make_content
from discussions.models import Comment
from progress.models import LessonProgress
from quizzes.models import QuizAttempt, Quiz


class LoginRequiredTests(TestCase):
    """Every account-management URL must bounce an anonymous visitor to
    login rather than ever rendering for them."""

    def test_anonymous_visitor_is_redirected_to_login(self):
        for name in ('account_settings', 'account_password_change', 'account_delete'):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('login'), response.url)


class ProfileEditTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='student', password='pass12345',
            first_name='Stu', last_name='Dent', email='old@example.com',
        )
        self.client.force_login(self.user)

    def test_get_renders_form_prefilled_with_current_values(self):
        response = self.client.get(reverse('account_settings'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Stu"')
        self.assertContains(response, 'value="student"')

    def test_valid_submission_updates_the_user(self):
        response = self.client.post(reverse('account_settings'), {
            'first_name': 'Student', 'last_name': 'Dent', 'username': 'student2',
        })
        self.assertRedirects(response, reverse('account_settings'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Student')
        self.assertEqual(self.user.username, 'student2')

    def test_resubmitting_unchanged_username_is_not_a_conflict_with_itself(self):
        response = self.client.post(reverse('account_settings'), {
            'first_name': 'Stu', 'last_name': 'Dent', 'username': 'student',
        })
        self.assertRedirects(response, reverse('account_settings'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'student')

    def test_changing_to_another_users_username_is_rejected(self):
        User.objects.create_user(username='taken', password='pass12345')
        response = self.client.post(reverse('account_settings'), {
            'first_name': 'Stu', 'last_name': 'Dent', 'username': 'taken',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())
        self.assertContains(
            response, 'That username is already taken. Please choose a different one.',
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, 'student')

    def test_email_is_not_editable_through_this_form(self):
        response = self.client.get(reverse('account_settings'))
        self.assertNotContains(response, 'name="email"')


class PasswordChangeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='student', password='old-pass-12345')
        self.client.force_login(self.user)

    def test_correct_old_password_changes_it_and_keeps_the_session(self):
        response = self.client.post(reverse('account_password_change'), {
            'old_password': 'old-pass-12345',
            'new_password1': 'a-new-strong-passw0rd',
            'new_password2': 'a-new-strong-passw0rd',
        })
        self.assertRedirects(response, reverse('account_settings'))

        # Session survived the change -- still logged in without re-authenticating.
        dash = self.client.get(reverse('dashboard'))
        self.assertEqual(dash.status_code, 200)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('a-new-strong-passw0rd'))

    def test_wrong_old_password_is_rejected(self):
        response = self.client.post(reverse('account_password_change'), {
            'old_password': 'not-the-real-password',
            'new_password1': 'a-new-strong-passw0rd',
            'new_password2': 'a-new-strong-passw0rd',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['form'].is_valid())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('old-pass-12345'))

        # Still logged in -- a failed attempt doesn't kill the session either.
        dash = self.client.get(reverse('dashboard'))
        self.assertEqual(dash.status_code, 200)

    def test_mismatched_new_passwords_are_rejected(self):
        response = self.client.post(reverse('account_password_change'), {
            'old_password': 'old-pass-12345',
            'new_password1': 'a-new-strong-passw0rd',
            'new_password2': 'a-different-passw0rd',
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('old-pass-12345'))


class AccountDeleteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(self.user)
        _, _, chapter, self.lesson = make_content()

        # One row in every app that FKs to User, to prove the cascade reaches
        # all of them -- not just the ones an ad hoc check happens to try.
        GoogleAccount.objects.create(user=self.user, google_id='g-1', email='student@example.com')
        Comment.objects.create(lesson=self.lesson, user=self.user, body='A doubt')
        LessonProgress.objects.create(user=self.user, lesson=self.lesson, watched=True)
        quiz = Quiz.objects.create(chapter=chapter, title='Quiz', pass_percentage=50)
        QuizAttempt.objects.create(user=self.user, quiz=quiz, score=1, total=1, passed=True)

    def test_wrong_password_does_not_delete_the_account(self):
        response = self.client.post(reverse('account_delete'), {'password': 'wrong-password'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

        # Still logged in -- a rejected attempt doesn't log the user out.
        dash = self.client.get(reverse('dashboard'))
        self.assertEqual(dash.status_code, 200)

    def test_correct_password_deletes_the_account_and_logs_out(self):
        response = self.client.post(reverse('account_delete'), {'password': 'pass12345'})
        self.assertRedirects(response, reverse('landing'))
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

        # Session is anonymous now -- a login_required page bounces to login.
        dash = self.client.get(reverse('dashboard'))
        self.assertEqual(dash.status_code, 302)
        self.assertIn(reverse('login'), dash.url)

    def test_deleting_the_account_cascades_to_every_related_row(self):
        self.client.post(reverse('account_delete'), {'password': 'pass12345'})
        self.assertFalse(GoogleAccount.objects.filter(google_id='g-1').exists())
        self.assertFalse(Comment.objects.filter(lesson=self.lesson).exists())
        self.assertFalse(LessonProgress.objects.filter(lesson=self.lesson).exists())
        self.assertFalse(QuizAttempt.objects.exists())
