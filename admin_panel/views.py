import logging

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.models import User
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from core.models import (
    Chapter, Choice, ClassLevel, Comment, Lesson,
    Question, Quiz, QuizAttempt, Resource, Subject,
)

from .forms import (
    ChapterForm, ChoiceForm, ClassLevelForm, LessonForm,
    QuestionForm, QuizForm, ResourceForm, SubjectForm,
)
from .mixins import AdminDeleteMixin, AdminFormMixin, AdminListMixin, StaffRequiredMixin

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

@staff_member_required
def dashboard(request):
    stats = {
        'subjects':  Subject.objects.count(),
        'classes':   ClassLevel.objects.count(),
        'chapters':  Chapter.objects.count(),
        'lessons':   Lesson.objects.count(),
        'users':     User.objects.count(),
        'comments':  Comment.objects.count(),
        'quizzes':   Quiz.objects.count(),
        'attempts':  QuizAttempt.objects.count(),
    }
    recent_users    = User.objects.order_by('-date_joined')[:5]
    recent_comments = Comment.objects.select_related('user', 'lesson').order_by('-created_at')[:5]
    recent_attempts = QuizAttempt.objects.select_related('user', 'quiz').order_by('-attempted_at')[:5]
    subjects        = Subject.objects.annotate(lesson_count=Count('class_levels__chapters__lessons')).all()

    return render(request, 'admin_panel/dashboard.html', {
        'stats': stats,
        'recent_users': recent_users,
        'recent_comments': recent_comments,
        'recent_attempts': recent_attempts,
        'subjects': subjects,
        'page': 'dashboard',
    })


# ─────────────────────────────────────────────
# SUBJECTS
# ─────────────────────────────────────────────

class SubjectListView(AdminListMixin, ListView):
    model = Subject
    context_object_name = 'subjects'
    template_name = 'admin_panel/subject_list.html'
    page = 'subjects'

    def get_queryset(self):
        return Subject.objects.annotate(
            class_count=Count('class_levels', distinct=True),
            lesson_count=Count('class_levels__chapters__lessons', distinct=True),
        ).order_by('name')


class SubjectCreateView(AdminFormMixin, SuccessMessageMixin, CreateView):
    model = Subject
    form_class = SubjectForm
    page = 'subjects'
    title = 'Add Subject'
    subtitle = 'Create a new subject (e.g. Mathematics, Physics)'
    back_url_name = 'ap:subject_list'
    success_message = 'Subject added successfully.'


class SubjectUpdateView(AdminFormMixin, SuccessMessageMixin, UpdateView):
    model = Subject
    form_class = SubjectForm
    page = 'subjects'
    subtitle = 'Update subject details'
    back_url_name = 'ap:subject_list'
    success_message = 'Subject "%(name)s" updated.'

    def get_title(self):
        return f'Edit Subject: {self.object.name}'


class SubjectDeleteView(AdminDeleteMixin, DeleteView):
    model = Subject
    obj_type = 'Subject'
    back_url_name = 'ap:subject_list'
    success_message = 'Subject "%(name)s" deleted.'
    page = 'subjects'


# ─────────────────────────────────────────────
# CLASS LEVELS
# ─────────────────────────────────────────────

class ClassLevelListView(AdminListMixin, ListView):
    model = ClassLevel
    context_object_name = 'class_levels'
    template_name = 'admin_panel/classlevel_list.html'
    page = 'classes'

    def get_queryset(self):
        qs = ClassLevel.objects.select_related('subject').annotate(
            chapter_count=Count('chapters', distinct=True),
            lesson_count=Count('chapters__lessons', distinct=True),
        ).order_by('subject__name', 'level')
        self.subject_filter = self.request.GET.get('subject')
        if self.subject_filter:
            qs = qs.filter(subject__slug=self.subject_filter)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['subjects'] = Subject.objects.all()
        context['subject_filter'] = self.subject_filter
        return context


class ClassLevelCreateView(AdminFormMixin, SuccessMessageMixin, CreateView):
    model = ClassLevel
    form_class = ClassLevelForm
    page = 'classes'
    title = 'Add Class Level'
    subtitle = 'Link a class (6–12) to a subject'
    back_url_name = 'ap:classlevel_list'
    success_message = 'Class level added successfully.'


class ClassLevelUpdateView(AdminFormMixin, SuccessMessageMixin, UpdateView):
    model = ClassLevel
    form_class = ClassLevelForm
    page = 'classes'
    subtitle = 'Update class level details'
    back_url_name = 'ap:classlevel_list'
    success_message = 'Class %(level)s updated.'

    def get_title(self):
        return f'Edit: {self.object}'


class ClassLevelDeleteView(AdminDeleteMixin, DeleteView):
    model = ClassLevel
    obj_type = 'Class Level'
    back_url_name = 'ap:classlevel_list'
    success_message = '%(obj)s deleted.'
    page = 'classes'


# ─────────────────────────────────────────────
# CHAPTERS
# ─────────────────────────────────────────────

class ChapterListView(AdminListMixin, ListView):
    model = Chapter
    context_object_name = 'chapters'
    template_name = 'admin_panel/chapter_list.html'
    page = 'chapters'

    def get_queryset(self):
        qs = Chapter.objects.select_related('class_level__subject').annotate(
            lesson_count=Count('lessons', distinct=True)
        ).order_by('class_level__subject__name', 'class_level__level', 'order')
        self.subject_filter = self.request.GET.get('subject')
        self.level_filter = self.request.GET.get('level')
        if self.subject_filter:
            qs = qs.filter(class_level__subject__slug=self.subject_filter)
        if self.level_filter:
            qs = qs.filter(class_level__level=self.level_filter)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'subjects': Subject.objects.all(),
            'subject_filter': self.subject_filter,
            'level_filter': self.level_filter,
            'level_choices': range(6, 13),
        })
        return context


class ChapterCreateView(AdminFormMixin, SuccessMessageMixin, CreateView):
    model = Chapter
    form_class = ChapterForm
    page = 'chapters'
    title = 'Add Chapter'
    subtitle = 'Add a chapter to a class level'
    back_url_name = 'ap:chapter_list'
    success_message = 'Chapter added successfully.'

    def form_valid(self, form):
        if not form.instance.slug:
            form.instance.slug = slugify(form.instance.title)
        return super().form_valid(form)


class ChapterUpdateView(AdminFormMixin, SuccessMessageMixin, UpdateView):
    model = Chapter
    form_class = ChapterForm
    page = 'chapters'
    subtitle = 'Update chapter details'
    back_url_name = 'ap:chapter_list'
    success_message = 'Chapter "%(title)s" updated.'

    def get_title(self):
        return f'Edit Chapter: {self.object.title}'

    def form_valid(self, form):
        # ChapterForm.slug is required=False (see admin_panel/forms.py) so
        # the "auto-fill from title if left blank" promise in its help text
        # holds on edit too, not just on create.
        if not form.instance.slug:
            form.instance.slug = slugify(form.instance.title)
        return super().form_valid(form)


class ChapterDeleteView(AdminDeleteMixin, DeleteView):
    model = Chapter
    obj_type = 'Chapter'
    back_url_name = 'ap:chapter_list'
    success_message = 'Chapter "%(title)s" deleted.'
    page = 'chapters'


# ─────────────────────────────────────────────
# LESSONS
# ─────────────────────────────────────────────

class LessonListView(AdminListMixin, ListView):
    model = Lesson
    context_object_name = 'lessons'
    template_name = 'admin_panel/lesson_list.html'
    page = 'lessons'

    def get_queryset(self):
        qs = Lesson.objects.select_related(
            'chapter__class_level__subject'
        ).annotate(
            comment_count=Count('comments', distinct=True),
            watch_count=Count('progress', distinct=True),
        ).order_by('chapter__class_level__subject__name', 'chapter__order', 'order')
        self.subject_filter = self.request.GET.get('subject')
        self.search = self.request.GET.get('q', '')
        if self.subject_filter:
            qs = qs.filter(chapter__class_level__subject__slug=self.subject_filter)
        if self.search:
            qs = qs.filter(
                Q(title__icontains=self.search) | Q(youtube_video_id__icontains=self.search)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'subjects': Subject.objects.all(),
            'subject_filter': self.subject_filter,
            'search': self.search,
        })
        return context


class LessonCreateView(AdminFormMixin, SuccessMessageMixin, CreateView):
    model = Lesson
    form_class = LessonForm
    page = 'lessons'
    title = 'Add Lesson'
    subtitle = 'Add a video lesson to a chapter'
    back_url_name = 'ap:lesson_list'
    success_message = 'Lesson added successfully.'
    help_text = (
        'YouTube Video ID is the part after ?v= in the URL. '
        'E.g. for https://youtube.com/watch?v=abc123, enter abc123'
    )

    def form_valid(self, form):
        if not form.instance.slug:
            form.instance.slug = slugify(form.instance.title)
        return super().form_valid(form)


class LessonUpdateView(AdminFormMixin, SuccessMessageMixin, UpdateView):
    model = Lesson
    form_class = LessonForm
    page = 'lessons'
    subtitle = 'Update lesson details'
    back_url_name = 'ap:lesson_list'
    success_message = 'Lesson "%(title)s" updated.'

    def get_title(self):
        return f'Edit Lesson: {self.object.title}'

    def form_valid(self, form):
        # See ChapterUpdateView.form_valid — LessonForm.slug is also
        # required=False, so the same "auto-fill if left blank" fallback
        # applies on edit as well as create.
        if not form.instance.slug:
            form.instance.slug = slugify(form.instance.title)
        return super().form_valid(form)


class LessonDeleteView(AdminDeleteMixin, DeleteView):
    model = Lesson
    obj_type = 'Lesson'
    back_url_name = 'ap:lesson_list'
    success_message = 'Lesson "%(title)s" deleted.'
    page = 'lessons'


# ─────────────────────────────────────────────
# RESOURCES
# ─────────────────────────────────────────────

class ResourceListView(AdminListMixin, ListView):
    model = Resource
    context_object_name = 'resources'
    template_name = 'admin_panel/resource_list.html'
    page = 'resources'

    def get_queryset(self):
        return Resource.objects.select_related(
            'lesson__chapter__class_level__subject'
        ).order_by('-uploaded_at')


class ResourceCreateView(AdminFormMixin, SuccessMessageMixin, CreateView):
    model = Resource
    form_class = ResourceForm
    page = 'resources'
    title = 'Upload Resource'
    subtitle = 'Attach a PDF or file to a lesson'
    back_url_name = 'ap:resource_list'
    success_message = 'Resource uploaded successfully.'


class ResourceDeleteView(AdminDeleteMixin, DeleteView):
    model = Resource
    obj_type = 'Resource'
    back_url_name = 'ap:resource_list'
    success_message = 'Resource "%(title)s" deleted.'
    page = 'resources'

    def form_valid(self, form):
        # Deleting the row doesn't delete the underlying file from storage —
        # that has to be done explicitly, before the row (and self.object's
        # DB-backed reference to it) is gone.
        self.object.file.delete(save=False)
        return super().form_valid(form)


# ─────────────────────────────────────────────
# QUIZZES
# ─────────────────────────────────────────────

class QuizListView(AdminListMixin, ListView):
    model = Quiz
    context_object_name = 'quizzes'
    template_name = 'admin_panel/quiz_list.html'
    page = 'quizzes'

    def get_queryset(self):
        return Quiz.objects.select_related('chapter__class_level__subject').annotate(
            q_count=Count('questions', distinct=True),
            attempt_count=Count('attempts', distinct=True),
        ).order_by('chapter__class_level__subject__name')


class QuizCreateView(AdminFormMixin, SuccessMessageMixin, CreateView):
    model = Quiz
    form_class = QuizForm
    page = 'quizzes'
    title = 'Create Quiz'
    subtitle = 'Create an MCQ quiz for a chapter'
    back_url_name = 'ap:quiz_list'
    success_message = 'Quiz created.'


class QuizUpdateView(AdminFormMixin, SuccessMessageMixin, UpdateView):
    model = Quiz
    form_class = QuizForm
    page = 'quizzes'
    subtitle = 'Update quiz settings'
    back_url_name = 'ap:quiz_list'
    success_message = 'Quiz "%(title)s" updated.'

    def get_title(self):
        return f'Edit Quiz: {self.object.title}'


class QuizDeleteView(AdminDeleteMixin, DeleteView):
    model = Quiz
    obj_type = 'Quiz'
    back_url_name = 'ap:quiz_list'
    success_message = 'Quiz "%(title)s" deleted.'
    page = 'quizzes'


@staff_member_required
def quiz_detail(request, pk):
    """View a quiz's questions and add/manage them."""
    quiz = get_object_or_404(Quiz, pk=pk)
    questions = quiz.questions.prefetch_related('choices').all()
    return render(request, 'admin_panel/quiz_detail.html', {
        'quiz': quiz, 'questions': questions, 'page': 'quizzes',
    })


# ─────────────────────────────────────────────
# QUESTIONS & CHOICES
# ─────────────────────────────────────────────

class QuestionCreateView(AdminFormMixin, CreateView):
    """Add a question to a specific quiz (quiz_pk comes from the URL, not
    from the submitted form — a question can't be reparented by tampering
    with POST data since the field isn't on the form at all)."""
    model = Question
    form_class = QuestionForm
    page = 'quizzes'
    subtitle = 'Write the question text'
    back_url_name = 'ap:quiz_detail'

    def dispatch(self, request, *args, **kwargs):
        self.quiz = get_object_or_404(Quiz, pk=kwargs['quiz_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_title(self):
        return f'Add Question to: {self.quiz.title}'

    def get_back_url_args(self):
        return [self.quiz.pk]

    def form_valid(self, form):
        form.instance.quiz = self.quiz
        response = super().form_valid(form)
        messages.success(self.request, 'Question added. Now add choices.')
        return response

    def get_success_url(self):
        # Deliberately not back_url_name — after adding a question, staff go
        # straight to adding its choices, not back to the quiz overview.
        return reverse('ap:choice_add', args=[self.object.pk])


class QuestionUpdateView(AdminFormMixin, SuccessMessageMixin, UpdateView):
    model = Question
    form_class = QuestionForm
    page = 'quizzes'
    title = 'Edit Question'
    subtitle = 'Update the question text or explanation'
    back_url_name = 'ap:quiz_detail'
    success_message = 'Question updated.'

    def get_back_url_args(self):
        return [self.object.quiz.pk]


class QuestionDeleteView(AdminDeleteMixin, DeleteView):
    model = Question
    obj_type = 'Question'
    back_url_name = 'ap:quiz_detail'
    success_message = 'Question deleted.'
    page = 'quizzes'

    def get_back_url_args(self):
        return [self.object.quiz.pk]


class ChoiceCreateView(StaffRequiredMixin, CreateView):
    """Choices get their own template (choice_add.html shows the form next
    to the running list of existing choices), so this doesn't use
    AdminFormMixin — that mixin's title/subtitle/back_url contract belongs
    to admin_panel/form.html, which this view never renders."""
    model = Choice
    form_class = ChoiceForm
    template_name = 'admin_panel/choice_add.html'
    page = 'quizzes'

    def dispatch(self, request, *args, **kwargs):
        self.question = get_object_or_404(Question, pk=kwargs['question_pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'question': self.question,
            'choices': self.question.choices.all(),
            'quiz': self.question.quiz,
        })
        return context

    def form_valid(self, form):
        form.instance.question = self.question
        response = super().form_valid(form)
        messages.success(self.request, 'Choice added.')
        return response

    def get_success_url(self):
        # Redirects back to itself so the freshly-added choice shows up in
        # the running list immediately — same as the old function view.
        return reverse('ap:choice_add', args=[self.question.pk])


class ChoiceDeleteView(AdminDeleteMixin, DeleteView):
    model = Choice
    obj_type = 'Choice'
    back_url_name = 'ap:choice_add'
    success_message = 'Choice deleted.'
    page = 'quizzes'

    def get_back_url_args(self):
        return [self.object.question.pk]


# ─────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────

class UserListView(AdminListMixin, ListView):
    model = User
    context_object_name = 'users'
    template_name = 'admin_panel/user_list.html'
    page = 'users'

    def get_queryset(self):
        qs = User.objects.annotate(
            progress_count=Count('progress', distinct=True),
            attempt_count=Count('quiz_attempts', distinct=True),
            comment_count=Count('comments', distinct=True),
        ).order_by('-date_joined')
        self.search = self.request.GET.get('q', '')
        if self.search:
            qs = qs.filter(
                Q(username__icontains=self.search) |
                Q(email__icontains=self.search) |
                Q(first_name__icontains=self.search) |
                Q(last_name__icontains=self.search)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search'] = self.search
        return context


@staff_member_required
@require_POST
def user_toggle_staff(request, pk):
    user = get_object_or_404(User, pk=pk)
    # Granting staff is a privilege escalation: a staff-only gate would let any
    # compromised staff account mint more staff accounts. Superusers only.
    if not request.user.is_superuser:
        logger.warning(
            'Non-superuser %r attempted to change staff status of %r',
            request.user.username, user.username,
        )
        messages.error(request, 'Only a superuser can change staff access.')
    elif user == request.user:
        messages.error(request, "You can't change your own staff status.")
    elif user.is_superuser:
        messages.error(request, "You can't change a superuser's staff status.")
    else:
        user.is_staff = not user.is_staff
        user.save(update_fields=['is_staff'])
        status = 'granted staff access to' if user.is_staff else 'removed staff access from'
        messages.success(request, f'Successfully {status} {user.username}.')
    return redirect('ap:user_list')


@staff_member_required
@require_POST
def user_toggle_active(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user == request.user:
        messages.error(request, "You can't deactivate yourself.")
    # Deactivating an admin is also an escalation vector (lock out the people
    # who could undo your changes), so staff can't switch off other staff.
    elif (user.is_staff or user.is_superuser) and not request.user.is_superuser:
        logger.warning(
            'Non-superuser %r attempted to deactivate admin account %r',
            request.user.username, user.username,
        )
        messages.error(request, 'Only a superuser can deactivate an admin account.')
    else:
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        status = 'activated' if user.is_active else 'deactivated'
        messages.success(request, f'User {user.username} {status}.')
    return redirect('ap:user_list')


# ─────────────────────────────────────────────
# COMMENTS
# ─────────────────────────────────────────────

class CommentListView(AdminListMixin, ListView):
    model = Comment
    context_object_name = 'comments'
    template_name = 'admin_panel/comment_list.html'
    page = 'comments'

    def get_queryset(self):
        return Comment.objects.select_related(
            'user', 'lesson__chapter__class_level__subject', 'parent'
        ).order_by('-created_at')


@staff_member_required
@require_POST
def comment_delete(request, pk):
    comment = get_object_or_404(Comment, pk=pk)
    comment.delete()
    messages.success(request, 'Comment deleted.')
    return redirect('ap:comment_list')
