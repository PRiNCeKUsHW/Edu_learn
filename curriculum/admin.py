from django.contrib import admin
from .models import CourseKind, Class, Subject, Chapter, Lesson, Resource


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
