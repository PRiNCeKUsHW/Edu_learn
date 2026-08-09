from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required

from curriculum.models import Chapter
from curriculum.views import _get_subject

from .models import Quiz, QuizAttempt


@login_required
def quiz_view(request, class_slug, subject_slug, chapter_slug):
    # Scoped through class -> subject -> chapter, same as lesson_detail.
    # Chapter.slug is only unique *within* a subject (see
    # Chapter.Meta.unique_together), so looking it up by slug alone would
    # raise MultipleObjectsReturned as soon as two chapters in different
    # classes happened to share a slug.
    klass, subject = _get_subject(class_slug, subject_slug)
    chapter = get_object_or_404(Chapter, subject=subject, slug=chapter_slug)
    quiz = get_object_or_404(Quiz, chapter=chapter)
    # Materialized once: `questions.count()` on an unevaluated queryset would
    # otherwise issue its own SELECT COUNT(*) instead of reusing the rows
    # prefetch_related just fetched.
    questions = list(quiz.questions.prefetch_related('choices').all())

    if request.method == 'POST':
        score = 0
        total = len(questions)
        results = []

        for question in questions:
            # `.all()` reads from the prefetch cache above; `.filter()`/`.get()`
            # on the related manager would each re-hit the database, silently
            # defeating the prefetch_related for every question in the quiz.
            choices = list(question.choices.all())
            selected_id = request.POST.get(f'question_{question.id}')
            correct_choice = next((c for c in choices if c.is_correct), None)
            selected_choice = None
            is_correct = False

            if selected_id:
                try:
                    selected_id = int(selected_id)
                except ValueError:
                    selected_id = None
                if selected_id is not None:
                    selected_choice = next((c for c in choices if c.id == selected_id), None)
                    if selected_choice is not None:
                        is_correct = selected_choice.is_correct
                        if is_correct:
                            score += 1

            results.append({
                'question': question,
                'selected': selected_choice,
                'correct': correct_choice,
                'is_correct': is_correct,
            })

        passed = (score / total * 100) >= quiz.pass_percentage if total > 0 else False
        attempt = QuizAttempt.objects.create(
            user=request.user, quiz=quiz,
            score=score, total=total, passed=passed
        )

        return render(request, 'quizzes/quiz_result.html', {
            'quiz': quiz,
            'results': results,
            'attempt': attempt,
        })

    return render(request, 'quizzes/quiz.html', {
        'quiz': quiz,
        'questions': questions,
        'chapter': chapter,
        'subject': subject,
        'klass': klass,
    })
