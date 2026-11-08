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
    # Set every time the lesson page is opened, watched or not -- what the
    # dashboard's "Recently watched" rail orders by. watched_at alone can't
    # serve that: most students never press "Mark watched".
    last_viewed_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        unique_together = ('user', 'lesson')

    def __str__(self):
        status = '✓' if self.watched else '○'
        return f'{status} {self.user.username} — {self.lesson.title}'
