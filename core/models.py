from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.utils.text import slugify

# ─────────────────────────────────────────────
# UPLOAD RULES
# ─────────────────────────────────────────────

MAX_RESOURCE_SIZE_MB = 25

# Study-material formats only. Deliberately excludes anything the browser will
# execute when opened from /media/ — .html, .htm, .svg, .xhtml, .js — since
# uploaded files are served from the same origin as the site.
ALLOWED_RESOURCE_EXTENSIONS = [
    'pdf',
    'doc', 'docx',
    'ppt', 'pptx',
    'xls', 'xlsx',
    'csv', 'txt', 'rtf',
    'png', 'jpg', 'jpeg', 'webp', 'gif',
    'zip',
]


def validate_resource_size(uploaded):
    """Cap upload size so one staff account can't fill the disk."""
    limit = MAX_RESOURCE_SIZE_MB * 1024 * 1024
    if uploaded.size > limit:
        raise ValidationError(
            'File is too large (%(actual).1f MB). The maximum is %(limit)s MB.',
            params={'actual': uploaded.size / (1024 * 1024), 'limit': MAX_RESOURCE_SIZE_MB},
        )


# ─────────────────────────────────────────────
# CURRICULUM HIERARCHY
# ─────────────────────────────────────────────

class CourseKind(models.Model):
    """
    A category of learning offering, defined entirely by the admin.

    Nothing is shipped: an empty install has zero kinds. Whoever runs the site
    creates whatever vocabulary fits it -- "School", "Coaching", "Bootcamp",
    "Workshop", "Certification" -- and attaches them to Classes.
    """
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=50,
        default='bi-collection',
        help_text="Bootstrap Icon class e.g. 'bi-mortarboard'",
    )
    color = models.CharField(
        max_length=7,
        default='#6366f1',
        validators=[RegexValidator(
            regex=r'^#[0-9A-Fa-f]{6}$',
            message='Enter a 6-digit hex colour, e.g. #6366f1.',
        )],
        help_text="Hex colour for this kind's badge, e.g. #6366f1.",
    )
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0, help_text='Display order.')

    class Meta:
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Class(models.Model):
    """
    The top of the hierarchy and the unit a student picks on the dashboard.

    Deliberately unopinionated about what a "class" is: it may be a school year
    ("Class 2"), an exam batch ("IIT JEE 2027"), a bootcamp ("Python Bootcamp"),
    or anything else. Nothing here is predefined -- every row is admin-created,
    so the same code runs a school, a coaching institute or a music academy.
    """
    name = models.CharField(max_length=150)
    slug = models.SlugField(unique=True, help_text='URL segment. Auto-filled from the name.')
    kind = models.ForeignKey(
        CourseKind,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='classes',
        # Optional so a class can be created before any kind exists -- nothing
        # is required up front. SET_NULL so deleting a kind never cascades into
        # losing lessons.
        help_text='Optional grouping, e.g. School or Bootcamp.',
    )
    description = models.TextField(blank=True)
    thumbnail = models.ImageField(
        upload_to='class_thumbnails/%Y/%m/',
        blank=True,
        null=True,
        # Same reasoning as Resource.file: these are served from /media/ on the
        # site's own origin, so keep to formats the browser renders as images
        # and never executes.
        validators=[FileExtensionValidator(['png', 'jpg', 'jpeg', 'webp'])],
    )
    icon = models.CharField(
        max_length=50,
        default='bi-mortarboard',
        help_text="Bootstrap Icon class, used when there is no thumbnail.",
    )
    is_active = models.BooleanField(
        default=True, help_text='Uncheck to hide from students without deleting.'
    )
    order = models.PositiveIntegerField(default=0, help_text='Display order.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'name']
        verbose_name_plural = 'classes'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Subject(models.Model):
    """A division of a Class: Maths under Class 2, Basics under Python Bootcamp."""
    klass = models.ForeignKey(
        # `class` is a Python keyword, so the field cannot be named for what it
        # holds. Templates read {{ subject.klass.name }}.
        Class, on_delete=models.CASCADE, related_name='subjects',
        verbose_name='class',
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(help_text='URL segment. Auto-filled from the name.')
    description = models.TextField(blank=True)
    icon_class = models.CharField(
        max_length=50,
        default='bi-book',
        help_text="Bootstrap Icon class e.g. 'bi-calculator'"
    )
    is_active = models.BooleanField(
        default=True, help_text='Uncheck to hide from students without deleting.'
    )
    order = models.PositiveIntegerField(default=0, help_text='Display order within the class.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', 'name']
        # Scoped, not global: two classes may each have their own "Maths".
        unique_together = ('klass', 'slug')

    def __str__(self):
        return f'{self.klass.name} - {self.name}'

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Chapter(models.Model):
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name='chapters'
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField()
    order = models.PositiveIntegerField(default=1)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['order']
        unique_together = ('subject', 'slug')

    def __str__(self):
        return f'{self.subject} › {self.title}'


class Lesson(models.Model):
    """
    A single video lesson. Stores the YouTube Video ID only.
    The embed URL is constructed via a model property.
    """
    chapter = models.ForeignKey(
        Chapter, on_delete=models.CASCADE, related_name='lessons'
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField()
    order = models.PositiveIntegerField(default=1)
    youtube_video_id = models.CharField(
        max_length=20,
        # This value is interpolated straight into the embed/thumbnail URL, so
        # keep it to the character set YouTube actually uses.
        validators=[RegexValidator(
            regex=r'^[A-Za-z0-9_-]{6,20}$',
            message='Enter just the video ID: 6–20 letters, digits, hyphen or underscore.',
        )],
        help_text="Only the Video ID from the YouTube URL, e.g. 'dQw4w9WgXcQ'"
    )
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order']
        unique_together = ('chapter', 'slug')

    def __str__(self):
        return f'{self.chapter.title} › {self.title}'

    @property
    def youtube_embed_url(self):
        return f'https://www.youtube.com/embed/{self.youtube_video_id}'

    @property
    def youtube_thumbnail_url(self):
        return f'https://img.youtube.com/vi/{self.youtube_video_id}/mqdefault.jpg'


# ─────────────────────────────────────────────
# RESOURCES (PDF Notes)
# ─────────────────────────────────────────────

class Resource(models.Model):
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name='resources'
    )
    title = models.CharField(max_length=200)
    file = models.FileField(
        upload_to='resources/%Y/%m/',
        validators=[
            FileExtensionValidator(allowed_extensions=ALLOWED_RESOURCE_EXTENSIONS),
            validate_resource_size,
        ],
        help_text=(
            f'Max {MAX_RESOURCE_SIZE_MB} MB. Allowed: '
            f'{", ".join(ALLOWED_RESOURCE_EXTENSIONS)}.'
        ),
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.lesson.title} — {self.title}'


# ─────────────────────────────────────────────
# PROGRESS TRACKING
# ─────────────────────────────────────────────

class LessonProgress(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='progress'
    )
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name='progress'
    )
    watched = models.BooleanField(default=False)
    watched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('user', 'lesson')

    def __str__(self):
        status = '✓' if self.watched else '○'
        return f'{status} {self.user.username} — {self.lesson.title}'


# ─────────────────────────────────────────────
# COMMENTS / DOUBTS
# ─────────────────────────────────────────────

class Comment(models.Model):
    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name='comments'
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


# ─────────────────────────────────────────────
# MCQ QUIZ
# ─────────────────────────────────────────────

class Quiz(models.Model):
    chapter = models.OneToOneField(
        Chapter, on_delete=models.CASCADE, related_name='quiz'
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    pass_percentage = models.PositiveIntegerField(
        default=60,
        validators=[MinValueValidator(1), MaxValueValidator(100)]
    )

    def __str__(self):
        return f'Quiz: {self.title}'

    def total_questions(self):
        return self.questions.count()


class Question(models.Model):
    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE, related_name='questions'
    )
    text = models.TextField()
    order = models.PositiveIntegerField(default=1)
    explanation = models.TextField(
        blank=True, help_text="Shown after the student answers"
    )

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f'Q{self.order}: {self.text[:60]}'


class Choice(models.Model):
    question = models.ForeignKey(
        Question, on_delete=models.CASCADE, related_name='choices'
    )
    text = models.CharField(max_length=300)
    is_correct = models.BooleanField(default=False)

    def __str__(self):
        marker = '✓' if self.is_correct else '✗'
        return f'[{marker}] {self.text[:50]}'


class QuizAttempt(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='quiz_attempts'
    )
    quiz = models.ForeignKey(
        Quiz, on_delete=models.CASCADE, related_name='attempts'
    )
    score = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    passed = models.BooleanField(default=False)
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-attempted_at']

    def __str__(self):
        return f'{self.user.username} — {self.quiz.title} ({self.score}/{self.total})'

    @property
    def percentage(self):
        return round((self.score / self.total) * 100) if self.total > 0 else 0


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
    # Always True in practice — core.google_oauth only ever creates this row
    # after checking the ID token's email_verified claim — but stored
    # explicitly rather than assumed, so there's an auditable record of why
    # this account was trusted to skip Django's own email verification.
    email_verified = models.BooleanField(default=True)
    linked_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user.username} ↔ Google ({self.email})'
