from django.contrib.auth.models import User
from django.db import models

# ─────────────────────────────────────────────
# GOOGLE OAUTH
# ─────────────────────────────────────────────

class GoogleAccount(models.Model):
    """Links a Django User to a Google account for OAuth sign-in.

    A one-to-one extension of the built-in User rather than a swap to a
    custom user model: AUTH_USER_MODEL can't safely be changed this late in
    an existing project (every other model here — LessonProgress, Comment,
    QuizAttempt — and the whole admin panel's user management already
    depend on the stock User). This is the standard, low-risk way to add
    OAuth identity onto an existing auth system.
    """
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='google_account'
    )
    # Google's own stable, permanent user identifier (the ID token's `sub`
    # claim) — not the email, which a person can change on their Google
    # account. This is what actually identifies "the same Google account"
    # across logins.
    google_id = models.CharField(max_length=255, unique=True, db_index=True)
    # The email Google reported at link time. Kept for display/audit; the
    # live email is still whatever's on the User record.
    email = models.EmailField()
    # Always True in practice — accounts.google_oauth only ever creates this
    # row after checking the ID token's email_verified claim — but stored
    # explicitly rather than assumed, so there's an auditable record of why
    # this account was trusted to skip Django's own email verification.
    email_verified = models.BooleanField(default=True)
    linked_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user.username} ↔ Google ({self.email})'
