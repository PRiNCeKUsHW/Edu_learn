from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('my-progress/', views.my_progress, name='my_progress'),
    path('enroll/<slug:class_slug>/', views.enroll, name='enroll'),
    path('lesson/<int:lesson_id>/mark-watched/', views.mark_watched, name='mark_watched'),
]
