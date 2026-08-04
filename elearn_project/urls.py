from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('panel/', include('admin_panel.urls', namespace='ap')),
]

if settings.DEBUG:
    # Dev convenience only. In production the web server (nginx/Apache) or a
    # storage backend must serve MEDIA_ROOT — Django's static() helper is
    # single-threaded, does no caching, and is explicitly unsuitable for it.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / 'static')
