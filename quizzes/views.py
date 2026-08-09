from django.http import Http404
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required

from curriculum.models import Chapter
from curriculum.views import _get_subject

from .models import Quiz, QuizAttempt, QuizAnswer


def _build_results(questions, selected_by_question_id):
    """Reconstructs the question/selected/correct/is_correct list
    quiz_result.html expects, from either freshly-submitted POST data or
    a QuizAttempt's stored QuizAnswer rows -- both call sites build the
    same `selected_by_question_id` dict shape ({question_id: Choice|None})
    and hand it here so the template-facing shape only exists in one place.
    """
    results = []
    for question in questions:
        # `.all()` reads from the prefetch cache set up by the caller;
        # `.filter()`/`.get()` on the related manager would each re-hit the
        # database, silently defeating the prefetch_related for every
        # question in the quiz.
        choices = list(question.choices.all())
        correct_choice = next((c for c in choices if c.is_correct), None)
        selected_choice = selected_by_question_id.get(question.id)
        is_correct = bool(selected_choice and selected_choice.is_correct)
        results.append({
            'question': question,
            'selected': selected_choice,
            'correct': correct_choice,
            'is_correct': is_correct,
        })
    return results


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
        selected_by_question_id = {}

        for question in questions:
            choices = list(question.choices.all())
            selected_id = request.POST.get(f'question_{question.id}')
            selected_choice = None

            if selected_id:
                try:
                    selected_id = int(selected_id)
                except ValueError:
                    selected_id = None
                if selected_id is not None:
                    selected_choice = next((c for c in choices if c.id == selected_id), None)
                    if selected_choice is not None and selected_choice.is_correct:
                        score += 1

            selected_by_question_id[question.id] = selected_choice

        results = _build_results(questions, selected_by_question_id)
        passed = (score / total * 100) >= quiz.pass_percentage if total > 0 else False
        # Every submission gets its own row -- history is kept so students
        # and staff can see improvement across retakes, not just the latest.
        attempt = QuizAttempt.objects.create(
            user=request.user, quiz=quiz,
            score=score, total=total, passed=passed
        )
        QuizAnswer.objects.bulk_create([
            QuizAnswer(
                attempt=attempt, question=r['question'],
                selected_choice=r['selected'], is_correct=r['is_correct'],
            )
            for r in results
        ])

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


@login_required
def quiz_analysis_view(request, class_slug, subject_slug, chapter_slug):
    """Reopens the result/answer-review screen for the student's most
    recent attempt at this quiz, without requiring a fresh submission."""
    klass, subject = _get_subject(class_slug, subject_slug)
    chapter = get_object_or_404(Chapter, subject=subject, slug=chapter_slug)
    quiz = get_object_or_404(Quiz, chapter=chapter)

    # QuizAttempt.Meta.ordering is already ['-attempted_at'].
    attempt = QuizAttempt.objects.filter(user=request.user, quiz=quiz).first()
    if attempt is None:
        raise Http404("No quiz attempt found for this quiz.")

    questions = list(quiz.questions.prefetch_related('choices').all())
    selected_by_question_id = {
        answer.question_id: answer.selected_choice
        for answer in attempt.answers.select_related('selected_choice')
    }
    results = _build_results(questions, selected_by_question_id)

    return render(request, 'quizzes/quiz_result.html', {
        'quiz': quiz,
        'results': results,
        'attempt': attempt,
    })
