from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class GoogleCompleteProfileForm(UserCreationForm):
    """Finishes account creation after a verified Google sign-in -- the only
    way a new account is created in this app. Deliberately just username +
    password: the email isn't a form field at all -- it comes from Google's
    verified ID token claims, held server-side in the session (see
    accounts.google_oauth / accounts.views.google_complete_profile), never
    re-submitted by the browser, so there's no way to tamper with it by
    editing form data.

    Everything else — passwords matching, AUTH_PASSWORD_VALIDATORS
    strength checks, the username's uniqueness — is inherited unchanged
    from UserCreationForm.
    """
    class Meta:
        model = User
        fields = ('username',)


class ProfileForm(forms.ModelForm):
    """Self-service profile edit. Includes `username` -- it's what
    login_view's AuthenticationForm actually authenticates against, so it's
    the field worth editing here. Deliberately excludes `email` instead: for
    a Google-linked account it's sourced from the verified ID token claim
    (see accounts.views.google_callback_view / GoogleAccount.email), and
    letting someone freely retype it here would just desync it from what
    Google actually verified.
    """
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'username')
        error_messages = {
            'username': {
                'unique': "That username is already taken. Please choose a different one.",
            },
        }
