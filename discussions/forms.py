from django import forms
from .models import Comment

# A doubt or a reply, not an essay. Enforced here rather than as a
# max_length on Comment.body so it needs no migration; every comment is
# created through this form (see curriculum.views.lesson_detail).
COMMENT_MAX_LENGTH = 2000


class CommentForm(forms.ModelForm):
    body = forms.CharField(
        label='',
        max_length=COMMENT_MAX_LENGTH,
        error_messages={
            'max_length': f'Comments can be at most {COMMENT_MAX_LENGTH} characters.',
        },
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Ask a doubt or leave a comment...',
            'class': 'form-control',
        }),
    )

    class Meta:
        model = Comment
        fields = ('body',)
