from django.urls import path
from . import views

urlpatterns = [
    # Search
    path('search/', views.search_view, name='search'),

    # Curriculum Hierarchy: Class → Subject → Chapter → Lesson.
    #
    # Every segment is a slug an admin chose. Nothing here assumes what a class
    # is, so /learn/class-2/maths/…, /learn/upsc/polity/… and
    # /learn/python-bootcamp/basics/… are all the same code path.
    path('learn/<slug:class_slug>/', views.subject_list, name='subject_list'),
    path('learn/<slug:class_slug>/<slug:subject_slug>/', views.chapter_list, name='chapter_list'),
    path(
        'learn/<slug:class_slug>/<slug:subject_slug>/<slug:chapter_slug>/<slug:lesson_slug>/',
        views.lesson_detail,
        name='lesson_detail'
    ),
]
