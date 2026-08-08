from django.contrib import admin
from .models import (
    CourseKind, Class, Subject, Chapter, Lesson, Resource,
    LessonProgress, Comment, Quiz, Question, Choice, QuizAttempt,
    GoogleAccount,
)


@admin.register(CourseKind)
class CourseKindAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'icon', 'color', 'is_active', 'order')
    list_filter = ('is_active',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


class SubjectInline(admin.TabularInline):
    model = Subject
    extra = 1
    fields = ('name', 'slug', 'icon_class', 'order', 'is_active')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Class)
class ClassAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'kind', 'is_active', 'order')
    list_filter = ('kind', 'is_active')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)
    inlines = [SubjectInline]


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'klass', 'slug', 'icon_class', 'is_active', 'order')
    list_filter = ('klass', 'is_active')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


class LessonInline(admin.TabularInline):
    model = Lesson
    extra = 1
    fields = ('title', 'slug', 'order', 'youtube_video_id', 'duration_minutes')
    prepopulated_fields = {'slug': ('title',)}


class ResourceInline(admin.TabularInline):
    model = Resource
    extra = 1


@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ('title', 'subject', 'order')
    list_filter = ('subject__klass', 'subject')
    prepopulated_fields = {'slug': ('title',)}
    inlines = [LessonInline]
    search_fields = ('title',)


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('title', 'chapter', 'order', 'youtube_video_id', 'duration_minutes')
    list_filter = ('chapter__subject__klass', 'chapter__subject')
    prepopulated_fields = {'slug': ('title',)}
    inlines = [ResourceInline]
    search_fields = ('title', 'youtube_video_id')


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ('user', 'lesson', 'watched', 'watched_at')
    list_filter = ('watched',)
    search_fields = ('user__username',)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('user', 'lesson', 'created_at', 'is_reply_display')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'body')

    @admin.display(boolean=True, description='Is Reply')
    def is_reply_display(self, obj):
        return obj.is_reply


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 4
    min_num = 2


class QuestionInline(admin.StackedInline):
    model = Question
    extra = 1


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ('title', 'chapter', 'pass_percentage', 'total_questions')
    inlines = [QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('text', 'quiz', 'order')
    inlines = [ChoiceInline]
    search_fields = ('text',)


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ('user', 'quiz', 'score', 'total', 'passed', 'attempted_at')
    list_filter = ('passed',)
    readonly_fields = ('attempted_at',)


@admin.register(GoogleAccount)
class GoogleAccountAdmin(admin.ModelAdmin):
    # Visibility only — google_id/email are set by the OAuth flow itself
    # (core/google_oauth.py) and shouldn't be hand-edited, since they're
    # what ties this row to a real, verified Google identity.
    list_display = ('user', 'email', 'email_verified', 'linked_at')
    list_filter = ('email_verified',)
    search_fields = ('user__username', 'email', 'google_id')
    readonly_fields = ('user', 'google_id', 'email', 'email_verified', 'linked_at')

    def has_add_permission(self, request):
        return False
