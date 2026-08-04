from django.urls import path
from . import views

urlpatterns = [
    # Public
    path('', views.landing, name='landing'),
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Dashboard
    path('dashboard/', views.dashboard, name='dashboard'),

    # Search
    path('search/', views.search_view, name='search'),

    # Curriculum Hierarchy
    path('learn/<slug:subject_slug>/', views.class_list, name='class_list'),
    path('learn/<slug:subject_slug>/class-<int:class_level>/', views.chapter_list, name='chapter_list'),
    path(
        'learn/<slug:subject_slug>/class-<int:class_level>/<slug:chapter_slug>/<slug:lesson_slug>/',
        views.lesson_detail,
        name='lesson_detail'
    ),

    # Actions
    path('lesson/<int:lesson_id>/mark-watched/', views.mark_watched, name='mark_watched'),

    # Quiz — scoped through subject + class level, because Chapter.slug is
    # only unique *within* a class level (see Chapter.Meta.unique_together).
    # A bare `quiz/<slug:chapter_slug>/` lookup can match two different
    # chapters in two different subjects/classes and raise
    # MultipleObjectsReturned the moment their slugs collide.
    #
    # Kept under its own `quiz/` prefix rather than nested under `learn/...`
    # deliberately: nesting it as `learn/<subject>/class-<n>/<chapter>/quiz/`
    # would give it the exact same shape as lesson_detail's
    # `<chapter_slug>/<lesson_slug>/` tail (a chapter slug is a valid slug
    # regex, and so is 'quiz') and lesson_detail is registered first, so
    # every quiz request would be swallowed by lesson_detail with 'quiz'
    # mistaken for a lesson slug.
    path(
        'quiz/<slug:subject_slug>/class-<int:class_level>/<slug:chapter_slug>/',
        views.quiz_view,
        name='quiz'
    ),
]
