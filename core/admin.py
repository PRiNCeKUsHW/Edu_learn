from django.contrib import admin
from .models import (
    Subject, ClassLevel, Chapter, Lesson, Resource,
    LessonProgress, Comment, Quiz, Question, Choice, QuizAttempt
)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'icon_class')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)


@admin.register(ClassLevel)
class ClassLevelAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'level', 'subject')
    list_filter = ('subject', 'level')


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
    list_display = ('title', 'class_level', 'order')
    list_filter = ('class_level__subject', 'class_level__level')
    prepopulated_fields = {'slug': ('title',)}
    inlines = [LessonInline]
    search_fields = ('title',)


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('title', 'chapter', 'order', 'youtube_video_id', 'duration_minutes')
    list_filter = ('chapter__class_level__subject', 'chapter__class_level__level')
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
