from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.db import models

# ─────────────────────────────────────────────
# COMMENTS / DOUBTS
# ─────────────────────────────────────────────

class Comment(models.Model):
    lesson = models.ForeignKey(
        'curriculum.Lesson', on_delete=models.CASCADE, related_name='comments'
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='comments'
    )
    parent = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.CASCADE, related_name='replies'
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.user.username} on "{self.lesson.title}"'

    def clean(self):
        """A reply must belong to the same lesson as its parent, and threads are
        one level deep (the template only renders parent -> replies)."""
        super().clean()
        if self.parent_id:
            if self.parent.lesson_id != self.lesson_id:
                raise ValidationError(
                    {'parent': 'A reply must be on the same lesson as its parent.'}
                )
            if self.parent.parent_id:
                raise ValidationError(
                    {'parent': 'Replies cannot be nested more than one level deep.'}
                )

    @property
    def is_reply(self):
        return self.parent is not None
