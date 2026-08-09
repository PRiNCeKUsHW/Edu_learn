"""Fixture helpers for the Class → Subject → Chapter → Lesson hierarchy.

Every test needs the full chain before it can assert anything about one level of
it, and the chain has changed shape twice now. Building it here means the next
change costs one file instead of forty setUp methods.

Each helper takes the parent it hangs off and returns the created row, so a test
that only cares about lessons can write:

    lesson = make_lesson(make_chapter(make_subject(make_class())))

Other apps' tests import from here too (`from curriculum.tests.factories import
...`) — the one deliberate exception to each app's tests being self-contained,
since every domain's tests need curriculum content to exist before they can
test anything of their own.
"""
from django.contrib.auth.models import User

from curriculum.models import Chapter, Class, CourseKind, Lesson, Subject
from quizzes.models import Choice, Question, Quiz


def make_kind(name='School', **kwargs):
    kwargs.setdefault('slug', name.lower().replace(' ', '-'))
    return CourseKind.objects.create(name=name, **kwargs)


def make_class(name='Class 6', **kwargs):
    """A top-level class. `kind` is optional, matching the model."""
    kwargs.setdefault('slug', name.lower().replace(' ', '-'))
    return Class.objects.create(name=name, **kwargs)


def make_subject(klass=None, name='Maths', **kwargs):
    kwargs.setdefault('slug', name.lower().replace(' ', '-'))
    return Subject.objects.create(klass=klass or make_class(), name=name, **kwargs)


def make_chapter(subject=None, title='Intro', **kwargs):
    kwargs.setdefault('slug', title.lower().replace(' ', '-'))
    kwargs.setdefault('order', 1)
    return Chapter.objects.create(subject=subject or make_subject(), title=title, **kwargs)


def make_lesson(chapter=None, title='Lesson 1', **kwargs):
    kwargs.setdefault('slug', title.lower().replace(' ', '-'))
    kwargs.setdefault('order', 1)
    kwargs.setdefault('youtube_video_id', 'dQw4w9WgXcQ')
    return Lesson.objects.create(chapter=chapter or make_chapter(), title=title, **kwargs)


def make_quiz(chapter=None, title='Chapter quiz', questions=1, **kwargs):
    """A quiz with `questions` two-choice questions, first choice correct."""
    quiz = Quiz.objects.create(chapter=chapter or make_chapter(), title=title, **kwargs)
    for index in range(questions):
        question = Question.objects.create(
            quiz=quiz, text=f'Question {index + 1}?', order=index + 1,
        )
        Choice.objects.create(question=question, text='Right', is_correct=True)
        Choice.objects.create(question=question, text='Wrong', is_correct=False)
    return quiz


def make_student(username='student', password='pass12345', **kwargs):
    return User.objects.create_user(username=username, password=password, **kwargs)


def make_content(class_name='Class 6', subject_name='Maths',
                 chapter_title='Intro', lesson_title='Lesson 1', **class_kwargs):
    """The whole chain in one call. Returns (klass, subject, chapter, lesson)."""
    klass = make_class(class_name, **class_kwargs)
    subject = make_subject(klass, subject_name)
    chapter = make_chapter(subject, chapter_title)
    lesson = make_lesson(chapter, lesson_title)
    return klass, subject, chapter, lesson
