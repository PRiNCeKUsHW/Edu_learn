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
