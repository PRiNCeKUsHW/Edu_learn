from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from .models import Comment


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=50, required=True)
    last_name = forms.CharField(max_length=50, required=True)

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'username', 'email', 'password1', 'password2')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        if commit:
            user.save()
        return user


class GoogleCompleteProfileForm(UserCreationForm):
    """Finishes account creation after a verified Google sign-in for a
    brand-new user. Deliberately just username + password: the email isn't
    a form field at all — it comes from Google's verified ID token claims,
    held server-side in the session (see core.google_oauth /
    core.views.google_complete_profile), never re-submitted by the browser,
    so there's no way to tamper with it by editing form data.

    Everything else — passwords matching, AUTH_PASSWORD_VALIDATORS
    strength checks, the username's uniqueness — is inherited unchanged
    from UserCreationForm, the same base RegisterForm already uses, so
    both signup paths enforce identical rules.
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
