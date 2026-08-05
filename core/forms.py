from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Comment


class GoogleCompleteProfileForm(UserCreationForm):
    """Finishes account creation after a verified Google sign-in -- the only
    way a new account is created in this app. Deliberately just username +
    password: the email isn't a form field at all -- it comes from Google's
    verified ID token claims, held server-side in the session (see
    core.google_oauth / core.views.google_complete_profile), never
    re-submitted by the browser, so there's no way to tamper with it by
    editing form data.

    Everything else — passwords matching, AUTH_PASSWORD_VALIDATORS
    strength checks, the username's uniqueness — is inherited unchanged
    from UserCreationForm.
    """
    class Meta:
        model = User
        fields = ('username',)


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ('body',)
        widgets = {
            'body': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Ask a doubt or leave a comment...',
                'class': 'form-control'
            })
        }
        labels = {'body': ''}
