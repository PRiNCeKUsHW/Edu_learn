from django.contrib import admin
from .models import Quiz, Question, Choice, QuizAttempt, QuizAnswer


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
