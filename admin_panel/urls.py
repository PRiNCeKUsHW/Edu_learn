from django.urls import path
from . import views

app_name = 'ap'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Course Kinds
    path('kinds/', views.CourseKindListView.as_view(), name='coursekind_list'),
    path('kinds/add/', views.CourseKindCreateView.as_view(), name='coursekind_add'),
    path('kinds/<int:pk>/edit/', views.CourseKindUpdateView.as_view(), name='coursekind_edit'),
    path('kinds/<int:pk>/delete/', views.CourseKindDeleteView.as_view(), name='coursekind_delete'),

    # Classes
    path('classes/', views.ClassListView.as_view(), name='class_list'),
    path('classes/add/', views.ClassCreateView.as_view(), name='class_add'),
    path('classes/<int:pk>/edit/', views.ClassUpdateView.as_view(), name='class_edit'),
    path('classes/<int:pk>/delete/', views.ClassDeleteView.as_view(), name='class_delete'),

    # Subjects
    path('subjects/', views.SubjectListView.as_view(), name='subject_list'),
    path('subjects/add/', views.SubjectCreateView.as_view(), name='subject_add'),
    path('subjects/<int:pk>/edit/', views.SubjectUpdateView.as_view(), name='subject_edit'),
    path('subjects/<int:pk>/delete/', views.SubjectDeleteView.as_view(), name='subject_delete'),

    # Chapters
    path('chapters/', views.ChapterListView.as_view(), name='chapter_list'),
    path('chapters/add/', views.ChapterCreateView.as_view(), name='chapter_add'),
    path('chapters/<int:pk>/edit/', views.ChapterUpdateView.as_view(), name='chapter_edit'),
    path('chapters/<int:pk>/delete/', views.ChapterDeleteView.as_view(), name='chapter_delete'),

    # Lessons
    path('lessons/', views.LessonListView.as_view(), name='lesson_list'),
    path('lessons/add/', views.LessonCreateView.as_view(), name='lesson_add'),
    path('lessons/<int:pk>/edit/', views.LessonUpdateView.as_view(), name='lesson_edit'),
    path('lessons/<int:pk>/delete/', views.LessonDeleteView.as_view(), name='lesson_delete'),

    # Resources
    path('resources/', views.ResourceListView.as_view(), name='resource_list'),
    path('resources/add/', views.ResourceCreateView.as_view(), name='resource_add'),
    path('resources/<int:pk>/delete/', views.ResourceDeleteView.as_view(), name='resource_delete'),

    # Quizzes
    path('quizzes/', views.QuizListView.as_view(), name='quiz_list'),
    path('quizzes/add/', views.QuizCreateView.as_view(), name='quiz_add'),
    path('quizzes/<int:pk>/', views.quiz_detail, name='quiz_detail'),
    path('quizzes/<int:pk>/edit/', views.QuizUpdateView.as_view(), name='quiz_edit'),
    path('quizzes/<int:pk>/delete/', views.QuizDeleteView.as_view(), name='quiz_delete'),

    # Questions
    path('quizzes/<int:quiz_pk>/questions/add/', views.QuestionCreateView.as_view(), name='question_add'),
    path('questions/<int:pk>/edit/', views.QuestionUpdateView.as_view(), name='question_edit'),
    path('questions/<int:pk>/delete/', views.QuestionDeleteView.as_view(), name='question_delete'),

    # Choices
    path('questions/<int:question_pk>/choices/', views.ChoiceCreateView.as_view(), name='choice_add'),
    path('choices/<int:pk>/delete/', views.ChoiceDeleteView.as_view(), name='choice_delete'),

    # Users
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/<int:pk>/toggle-staff/', views.user_toggle_staff, name='user_toggle_staff'),
    path('users/<int:pk>/toggle-active/', views.user_toggle_active, name='user_toggle_active'),

    # Comments
    path('comments/', views.CommentListView.as_view(), name='comment_list'),
    path('comments/<int:pk>/delete/', views.comment_delete, name='comment_delete'),
]
