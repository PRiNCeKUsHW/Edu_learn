from django.contrib.auth.models import User
from django.db import models

# ─────────────────────────────────────────────
# PROGRESS TRACKING
# ─────────────────────────────────────────────

class LessonProgress(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='progress'
    )
    lesson = models.ForeignKey(
        'curriculum.Lesson', on_delete=models.CASCADE, related_name='progress'
    )
    watched = models.BooleanField(default=False)
    watched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('user', 'lesson')

    def __str__(self):
        status = '✓' if self.watched else '○'
        return f'{status} {self.user.username} — {self.lesson.title}'
