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


# ─────────────────────────────────────────────
# ENROLLMENT
# ─────────────────────────────────────────────

class Enrollment(models.Model):
    """One student's membership of one course (Class).

    Before this existed, every active class was shown to every logged-in
    student, so the dashboard read as "you are enrolled in everything".
    Enrolling is now an explicit, per-course act.

    Enrollment scopes what a student *sees*; it is not an access control
    boundary. Lesson and quiz URLs remain reachable if deep-linked, which is
    the deliberate limit of this change.
    """
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='enrollments'
    )
    # `klass`, not `class`: the latter is a Python keyword. Matches
    # Subject.klass in curriculum.models.
    klass = models.ForeignKey(
        'curriculum.Class', on_delete=models.CASCADE, related_name='enrollments'
    )
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Makes re-enrolling structurally impossible rather than merely
        # discouraged in the view; the view's get_or_create then turns a
        # repeat click into a no-op instead of an IntegrityError.
        unique_together = ('user', 'klass')
        ordering = ['-enrolled_at']

    def __str__(self):
        return f'{self.user.username} — {self.klass.name}'
