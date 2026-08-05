from django import forms
from django.utils.text import slugify

from core.models import Subject, ClassLevel, Chapter, Lesson, Resource, Quiz, Question, Choice


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


class SubjectForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Subject
        fields = ('name', 'slug', 'description', 'icon_class')
        help_texts = {
            'slug': 'URL-friendly name. Auto-filled from name. E.g. "mathematics"',
            'icon_class': 'Bootstrap Icons class. E.g. bi-calculator, bi-atom, bi-book',
        }


class ClassLevelForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ClassLevel
        fields = ('subject', 'level', 'description')


class ChapterForm(StyledFormMixin, forms.ModelForm):
    # Chapter.slug has no blank=True, so ModelForm would normally make it a
    # required field — rejecting an empty submission before we could ever
    # fall back to the title. required=False lets a blank submission reach
    # clean() below.
    slug = forms.SlugField(required=False)

    class Meta:
        model = Chapter
        fields = ('class_level', 'title', 'slug', 'order', 'description')
        help_texts = {
            'slug': 'Auto-filled from title if left blank.',
            'order': 'Display order within the class level.',
        }

    def clean(self):
        # Filled in here, not in the view's form_valid(), because ModelForm
        # validates unique_together during _post_clean() -- which runs right
        # after this method, against whatever is in cleaned_data at that
        # point. Generating the slug in the view (after is_valid() already
        # passed) meant a collision between two auto-generated slugs skipped
        # that check entirely and hit the database as a raw IntegrityError
        # instead of a normal "already exists" form error.
        cleaned_data = super().clean()
        if not cleaned_data.get('slug') and cleaned_data.get('title'):
            cleaned_data['slug'] = slugify(cleaned_data['title'])
        return cleaned_data


class LessonForm(StyledFormMixin, forms.ModelForm):
    # Same reasoning as ChapterForm.slug above — Lesson.slug has no
    # blank=True either.
    slug = forms.SlugField(required=False)

    class Meta:
        model = Lesson
        fields = ('chapter', 'title', 'slug', 'order', 'youtube_video_id', 'description', 'duration_minutes')
        help_texts = {
            'youtube_video_id': 'Only the ID part of the YouTube URL. E.g. for https://youtube.com/watch?v=dQw4w9WgXcQ enter: dQw4w9WgXcQ',
            'slug': 'Auto-filled from title if left blank.',
        }

    def clean(self):
        # See ChapterForm.clean — same fix, same reason: fill the slug
        # before unique_together validation runs, not after.
        cleaned_data = super().clean()
        if not cleaned_data.get('slug') and cleaned_data.get('title'):
            cleaned_data['slug'] = slugify(cleaned_data['title'])
        return cleaned_data


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
