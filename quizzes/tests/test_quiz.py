"""Chapter quizzes: scoring correctness and the two regressions this pass
fixed — the duplicate-slug crash and the prefetch-defeating N+1.
"""
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from curriculum.models import Chapter
from quizzes.models import Choice, Question, Quiz, QuizAttempt
from curriculum.tests.factories import make_chapter, make_class, make_subject


class QuizScoringTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(self.user)

        chapter = make_chapter(make_subject(make_class(), 'Maths'), 'Numbers')
        self.quiz = Quiz.objects.create(chapter=chapter, title='Numbers Quiz', pass_percentage=60)
        self.url = reverse('quiz', args=['class-6', 'maths', 'numbers'])

        self.q1 = Question.objects.create(quiz=self.quiz, text='2 + 2 = ?', order=1)
        self.q1_right = Choice.objects.create(question=self.q1, text='4', is_correct=True)
        self.q1_wrong = Choice.objects.create(question=self.q1, text='5', is_correct=False)

        self.q2 = Question.objects.create(quiz=self.quiz, text='3 + 3 = ?', order=2)
        self.q2_right = Choice.objects.create(question=self.q2, text='6', is_correct=True)
        self.q2_wrong = Choice.objects.create(question=self.q2, text='7', is_correct=False)

    def _submit(self, q1_choice=None, q2_choice=None):
        data = {}
        if q1_choice is not None:
            data[f'question_{self.q1.id}'] = q1_choice
        if q2_choice is not None:
            data[f'question_{self.q2.id}'] = q2_choice
        return self.client.post(self.url, data)

    def test_all_correct_scores_full_marks_and_passes(self):
        response = self._submit(self.q1_right.id, self.q2_right.id)
        attempt = QuizAttempt.objects.get()
        self.assertEqual(attempt.score, 2)
        self.assertEqual(attempt.total, 2)
        self.assertTrue(attempt.passed)
        self.assertContains(response, 'You passed')

    def test_all_wrong_scores_zero_and_fails(self):
        self._submit(self.q1_wrong.id, self.q2_wrong.id)
        attempt = QuizAttempt.objects.get()
        self.assertEqual(attempt.score, 0)
        self.assertFalse(attempt.passed)

    def test_unanswered_question_counts_as_incorrect_not_a_crash(self):
        response = self._submit(self.q1_right.id, q2_choice=None)
        self.assertEqual(response.status_code, 200)
        attempt = QuizAttempt.objects.get()
        self.assertEqual(attempt.score, 1)
        self.assertEqual(attempt.total, 2)

    def test_pass_percentage_boundary(self):
        # 1/2 = 50%, pass mark is 60% -> fail.
        self._submit(self.q1_right.id, self.q2_wrong.id)
        self.assertFalse(QuizAttempt.objects.get().passed)

    def test_non_numeric_choice_id_does_not_crash(self):
        response = self.client.post(self.url, {
            f'question_{self.q1.id}': 'not-a-number',
            f'question_{self.q2.id}': self.q2_right.id,
        })
        self.assertEqual(response.status_code, 200)
        attempt = QuizAttempt.objects.get()
        self.assertEqual(attempt.score, 1)

    def test_choice_from_a_different_question_is_not_accepted(self):
        """A crafted POST substituting another question's choice id must not
        score as correct — the lookup is scoped to that question's own
        prefetched choices, not a global Choice.objects.get()."""
        response = self.client.post(self.url, {
            f'question_{self.q1.id}': self.q2_right.id,  # wrong question's choice
            f'question_{self.q2.id}': self.q2_right.id,
        })
        self.assertEqual(response.status_code, 200)
        attempt = QuizAttempt.objects.get()
        self.assertEqual(attempt.score, 1)  # only q2 counts


class QuizQueryCountTests(TestCase):
    """Locks in the Task 7 fix: submitting a quiz must not issue more
    queries as the number of questions grows. Before the fix this scaled as
    2N+3; a regression back to that pattern would fail this test."""

    def setUp(self):
        self.user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(self.user)

        chapter = make_chapter(make_subject(make_class(), 'Maths'), 'Numbers')
        self.quiz = Quiz.objects.create(chapter=chapter, title='Numbers Quiz', pass_percentage=60)
        self.url = reverse('quiz', args=['class-6', 'maths', 'numbers'])

        self.questions = []
        for i in range(8):
            q = Question.objects.create(quiz=self.quiz, text=f'Q{i}', order=i)
            Choice.objects.create(question=q, text='right', is_correct=True)
            Choice.objects.create(question=q, text='wrong', is_correct=False)
            self.questions.append(q)

    def test_submission_query_count_is_independent_of_question_count(self):
        data = {f'question_{q.id}': q.choices.first().id for q in self.questions}
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        # Regardless of the 8 questions above: subject, class level, chapter,
        # quiz, the questions+choices prefetch (2 queries), the QuizAttempt
        # insert, and the session/auth lookups the test client does on every
        # request — a small constant, not one that grows with question count.
        self.assertLess(len(ctx.captured_queries), 15)


class QuizDuplicateSlugTests(TestCase):
    """Two chapters in different subjects/classes sharing a slug must not
    crash the quiz view — each must resolve to its own chapter's quiz."""

    def setUp(self):
        self.user = User.objects.create_user(username='student', password='pass12345')
        self.client.force_login(self.user)

        klass = make_class('Class 6')
        self.maths = make_subject(klass, 'Maths')
        self.physics = make_subject(klass, 'Physics')

        # Same slug, same class level number, different subjects — this used
        # to be enough to trigger MultipleObjectsReturned.
        self.maths_chapter = Chapter.objects.create(
            subject=self.maths, title='Introduction', slug='introduction', order=1,
        )
        self.physics_chapter = Chapter.objects.create(
            subject=self.physics, title='Introduction', slug='introduction', order=1,
        )

        self.maths_quiz = Quiz.objects.create(
            chapter=self.maths_chapter, title='Maths Intro Quiz', pass_percentage=50,
        )
        self.physics_quiz = Quiz.objects.create(
            chapter=self.physics_chapter, title='Physics Intro Quiz', pass_percentage=50,
        )
        q = Question.objects.create(quiz=self.maths_quiz, text='2 + 2 = ?', order=1)
        self.correct_choice = Choice.objects.create(question=q, text='4', is_correct=True)
        Choice.objects.create(question=q, text='5', is_correct=False)
        self.question = q

    def test_each_chapter_resolves_to_its_own_quiz(self):
        maths_url = reverse('quiz', args=['class-6', 'maths', 'introduction'])
        physics_url = reverse('quiz', args=['class-6', 'physics', 'introduction'])

        maths_resp = self.client.get(maths_url)
        physics_resp = self.client.get(physics_url)

        self.assertEqual(maths_resp.status_code, 200)
        self.assertEqual(physics_resp.status_code, 200)
        self.assertContains(maths_resp, 'Maths Intro Quiz')
        self.assertContains(physics_resp, 'Physics Intro Quiz')

    def test_unknown_subject_scope_404s_instead_of_crossing_over(self):
        response = self.client.get(reverse('quiz', args=['class-6', 'chemistry', 'introduction']))
        self.assertEqual(response.status_code, 404)

    def test_quiz_submission_still_scores_correctly(self):
        url = reverse('quiz', args=['class-6', 'maths', 'introduction'])
        response = self.client.post(url, {f'question_{self.question.id}': self.correct_choice.id})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'You passed')
