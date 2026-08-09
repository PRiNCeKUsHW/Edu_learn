from django import forms
from django.utils.text import slugify

from curriculum.models import CourseKind, Class, Subject, Chapter, Lesson, Resource
from quizzes.models import Quiz, Question, Choice


class StyledFormMixin:
    """Adds Bootstrap classes to all fields automatically."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            widget = field.widget
            existing = widget.attrs.get('class', '')
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs['class'] = f'{existing} form-check-input'.strip()
            elif isinstance(widget, forms.Select):
                widget.attrs['class'] = f'{existing} form-select'.strip()
            elif isinstance(widget, forms.Textarea):
                widget.attrs['class'] = f'{existing} form-control'.strip()
                widget.attrs.setdefault('rows', 3)
            else:
                widget.attrs['class'] = f'{existing} form-control'.strip()


class SlugFromNameMixin:
    """Fill a blank `slug` from another field during clean().

    Deliberately here and not in the view's form_valid(): ModelForm validates
    uniqueness during _post_clean(), which runs right after this method against
    whatever is in cleaned_data at that point. Generating the slug in the view
    (after is_valid() already passed) means a collision between two
    auto-generated slugs skips that check entirely and hits the database as a
    raw IntegrityError instead of a normal "already exists" form error.
    """
    slug_source = 'name'
    slug_fallback = 'item'

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('slug'):
            source = cleaned_data.get(self.slug_source)
            if source:
                cleaned_data['slug'] = slugify(source) or self.slug_fallback
        return cleaned_data


class CourseKindForm(SlugFromNameMixin, StyledFormMixin, forms.ModelForm):
    slug = forms.SlugField(required=False)

    class Meta:
        model = CourseKind
        fields = ('name', 'slug', 'icon', 'color', 'order', 'is_active', 'description')
        help_texts = {
            'name': 'E.g. School, Coaching, Bootcamp, Workshop, Certification.',
            'slug': 'Auto-filled from the name if left blank.',
            'icon': 'Bootstrap Icons class. E.g. bi-mortarboard, bi-rocket-takeoff',
            'color': 'Hex colour for the badge shown on class cards.',
        }
        widgets = {'color': forms.TextInput(attrs={'type': 'color'})}


class ClassForm(SlugFromNameMixin, StyledFormMixin, forms.ModelForm):
    slug = forms.SlugField(required=False)

    class Meta:
        model = Class
        fields = (
            'name', 'slug', 'kind', 'icon', 'thumbnail',
            'order', 'is_active', 'description',
        )
        help_texts = {
            'name': 'Anything you like: Class 2, UPSC Batch, IIT JEE 2027, Python Bootcamp.',
            'slug': 'Auto-filled from the name if left blank.',
            'icon': 'Bootstrap Icons class, used when there is no thumbnail.',
            'thumbnail': 'Optional cover image (PNG, JPG or WebP).',
        }


class SubjectForm(SlugFromNameMixin, StyledFormMixin, forms.ModelForm):
    slug = forms.SlugField(required=False)

    class Meta:
        model = Subject
        fields = ('klass', 'name', 'slug', 'icon_class', 'order', 'is_active', 'description')
        help_texts = {
            'name': 'A division of the class, e.g. Maths, Physics, Basics.',
            'slug': 'Auto-filled from the name if left blank.',
            'icon_class': 'Bootstrap Icons class. E.g. bi-calculator, bi-atom, bi-book',
        }


class ChapterForm(SlugFromNameMixin, StyledFormMixin, forms.ModelForm):
    # Chapter.slug has no blank=True, so ModelForm would normally make it a
    # required field — rejecting an empty submission before we could ever
    # fall back to the title. required=False lets a blank submission reach
    # SlugFromNameMixin.clean().
    slug = forms.SlugField(required=False)
    slug_source = 'title'
    slug_fallback = 'chapter'

    class Meta:
        model = Chapter
        fields = ('subject', 'title', 'slug', 'order', 'description')
        help_texts = {
            'slug': 'Auto-filled from title if left blank.',
            'order': 'Display order within the subject.',
        }


class LessonForm(SlugFromNameMixin, StyledFormMixin, forms.ModelForm):
    # Same reasoning as ChapterForm.slug above — Lesson.slug has no
    # blank=True either.
    slug = forms.SlugField(required=False)
    slug_source = 'title'
    slug_fallback = 'lesson'

    class Meta:
        model = Lesson
        fields = ('chapter', 'title', 'slug', 'order', 'youtube_video_id', 'description', 'duration_minutes')
        help_texts = {
            'youtube_video_id': 'Only the ID part of the YouTube URL. E.g. for https://youtube.com/watch?v=dQw4w9WgXcQ enter: dQw4w9WgXcQ',
            'slug': 'Auto-filled from title if left blank.',
        }


class ResourceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Resource
        fields = ('lesson', 'title', 'file')


class QuizForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Quiz
        fields = ('chapter', 'title', 'description', 'pass_percentage')
        help_texts = {
            'pass_percentage': 'Minimum percentage required to pass (1–100).',
        }


class QuestionForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Question
        fields = ('text', 'order', 'explanation')
        help_texts = {
            'explanation': 'Shown to students after they answer. Optional but recommended.',
        }
        widgets = {
            'text': forms.Textarea(attrs={'rows': 3}),
            'explanation': forms.Textarea(attrs={'rows': 2}),
        }


class ChoiceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Choice
        fields = ('text', 'is_correct')
        help_texts = {
            'is_correct': 'Check this for the correct answer.',
        }
