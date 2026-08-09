from django.contrib import admin
from .models import Comment


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ('user', 'lesson', 'created_at', 'is_reply_display')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'body')

    @admin.display(boolean=True, description='Is Reply')
    def is_reply_display(self, obj):
        return obj.is_reply
