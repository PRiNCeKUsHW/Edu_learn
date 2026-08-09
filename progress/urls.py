from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('lesson/<int:lesson_id>/mark-watched/', views.mark_watched, name='mark_watched'),
]
