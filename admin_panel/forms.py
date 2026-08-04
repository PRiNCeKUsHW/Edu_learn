from django import forms
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
    # required field — rejecting an empty submission before the view's
    # "auto-fill from title if left blank" fallback ever runs. The help text
    # already promises that fallback; this override is what makes it real.
    slug = forms.SlugField(required=False)

    class Meta:
        model = Chapter
        fields = ('class_level', 'title', 'slug', 'order', 'description')
        help_texts = {
            'slug': 'Auto-filled from title if left blank.',
            'order': 'Display order within the class level.',
        }


class LessonForm(StyledFormMixin, forms.ModelForm):
    # Same reasoning as ChapterForm.slug above — Lesson.slug has no
    # blank=True either, so this override is what makes the "auto-filled
    # from title if left blank" help text actually true.
    slug = forms.SlugField(required=False)

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
