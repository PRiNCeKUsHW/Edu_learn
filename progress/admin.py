from django.contrib import admin
from .models import LessonProgress


@admin.register(LessonProgress)
class LessonProgressAdmin(admin.ModelAdmin):
    list_display = ('user', 'lesson', 'watched', 'watched_at')
    list_filter = ('watched',)
    search_fields = ('user__username',)
