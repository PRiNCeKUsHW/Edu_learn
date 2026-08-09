from django.urls import path
from . import views

urlpatterns = [
    # Scoped through class + subject, because Chapter.slug is only unique
    # *within* a subject (see Chapter.Meta.unique_together). A bare
    # `quiz/<slug:chapter_slug>/` lookup can match two different chapters in
    # two different classes and raise MultipleObjectsReturned the moment
    # their slugs collide.
    path(
        'quiz/<slug:class_slug>/<slug:subject_slug>/<slug:chapter_slug>/',
        views.quiz_view,
        name='quiz'
    ),
    path(
        'quiz/<slug:class_slug>/<slug:subject_slug>/<slug:chapter_slug>/analysis/',
        views.quiz_analysis_view,
        name='quiz_analysis'
    ),
]
