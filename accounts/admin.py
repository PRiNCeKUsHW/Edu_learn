from django.contrib import admin
from .models import GoogleAccount


@admin.register(GoogleAccount)
class GoogleAccountAdmin(admin.ModelAdmin):
    # Visibility only — google_id/email are set by the OAuth flow itself
    # (accounts/google_oauth.py) and shouldn't be hand-edited, since they're
    # what ties this row to a real, verified Google identity.
    list_display = ('user', 'email', 'email_verified', 'linked_at')
    list_filter = ('email_verified',)
    search_fields = ('user__username', 'email', 'google_id')
    readonly_fields = ('user', 'google_id', 'email', 'email_verified', 'linked_at')

    def has_add_permission(self, request):
        return False
