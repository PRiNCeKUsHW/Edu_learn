from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing, name='landing'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Google OAuth ("Continue with Google"). The callback path must exactly
    # match GOOGLE_OAUTH_REDIRECT_URI (settings.py / .env) and whatever is
    # registered as an authorized redirect URI on the Google Cloud OAuth
    # client — Google rejects the exchange otherwise.
    path('accounts/google/login/', views.google_login_view, name='google_login'),
    path('accounts/google/callback/', views.google_callback_view, name='google_callback'),
    path(
        'accounts/google/complete-profile/',
        views.google_complete_profile_view,
        name='google_complete_profile',
    ),
    path('accounts/google/link/', views.google_link_confirm_view, name='google_link_confirm'),
]
