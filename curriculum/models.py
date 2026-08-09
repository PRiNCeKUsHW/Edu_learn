from django.core.exceptions import ValidationError
from django.db import models
from django.core.validators import FileExtensionValidator, RegexValidator
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
    slug = models.SlugField(max_length=100, unique=True)
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
    slug = models.SlugField(max_length=100, unique=True, help_text='URL segment. Auto-filled from the name.')
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
    slug = models.SlugField(max_length=100, help_text='URL segment. Auto-filled from the name.')
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
    slug = models.SlugField(max_length=100)
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
    slug = models.SlugField(max_length=100)
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
