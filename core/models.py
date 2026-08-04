from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)

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

class Subject(models.Model):
    """Scalable: start with Math, add Physics, Chemistry, etc. later."""
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    icon_class = models.CharField(
        max_length=50,
        default='bi-book',
        help_text="Bootstrap Icon class e.g. 'bi-calculator'"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ClassLevel(models.Model):
    """Represents Class 6 through Class 12."""
    CLASS_CHOICES = [(i, f'Class {i}') for i in range(6, 13)]

    level = models.IntegerField(
        choices=CLASS_CHOICES,
        validators=[MinValueValidator(6), MaxValueValidator(12)]
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name='class_levels'
    )
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['level']
        unique_together = ('level', 'subject')

    def __str__(self):
        return f'Class {self.level} — {self.subject.name}'


class Chapter(models.Model):
    class_level = models.ForeignKey(
        ClassLevel, on_delete=models.CASCADE, related_name='chapters'
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField()
    order = models.PositiveIntegerField(default=1)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['order']
        unique_together = ('class_level', 'slug')

    def __str__(self):
        return f'{self.class_level} › {self.title}'


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
