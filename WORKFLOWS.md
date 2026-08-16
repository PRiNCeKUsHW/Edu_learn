# WORKFLOWS.md

Important business workflows, describing current behavior end to end. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the auth sequence diagram and
[API.md](API.md) for the routes referenced here.

## 1. New Student Sign-Up (Google-only)

1. Visitor hits `/register/`. If `GOOGLE_OAUTH_CONFIGURED` is `False`
   (any of the three `GOOGLE_OAUTH_*` env vars missing), the page shows a
   "sign-up temporarily unavailable" message instead of a button — no other
   part of the app breaks.
2. Clicks "Continue with Google" → `/accounts/google/login/` → redirect to
   Google with a random `state` stashed in the session.
3. Google authenticates the user, redirects back to
   `/accounts/google/callback/` with `code` and `state`.
4. `state` is compared (constant-time); `code` is exchanged server-side for
   a verified ID token (`accounts/google_oauth.py`); `email_verified` must
   be `True` or the flow is rejected.
5. No existing `GoogleAccount` for this Google `sub`, and no existing
   `User` shares this email → claims are stashed in
   `session['pending_google']` (10-minute TTL) and the browser is sent to
   `/accounts/google/complete-profile/`.
6. User picks a username + password (email/name come from Google, not
   re-entered). On submit: `User` and `GoogleAccount` are created inside
   `transaction.atomic()`; a concurrent duplicate submit is caught via the
   `google_id` unique constraint (`IntegrityError` → "already linked,
   please sign in").
7. User is logged in and redirected to `/dashboard/`.

## 2. Returning Google User

Same steps 2–4 above, but a `GoogleAccount` already exists for the Google
`sub` → the user is logged straight in and redirected to `/dashboard/`
(skips steps 5–6 entirely).

## 3. Linking Google to an Existing Password Account

If the callback's email matches **exactly one** existing password-based
`User` (no `GoogleAccount` for that email yet), the user is routed to
`/accounts/google/link/` instead of profile completion — asked once
whether to link. Confirming creates the `GoogleAccount` and logs them in;
declining leaves the password login untouched, no `GoogleAccount` created.
If the email matches **two or more** existing users, linking is skipped
entirely (unresolvable ambiguity, logged as a warning) and the flow falls
back to new-user signup instead of guessing which account to link.

## 4. Password Login

`/login/` → Django's `AuthenticationForm` → on success, redirect to
`?next=` if it's a same-host/same-scheme URL (validated via
`url_has_allowed_host_and_scheme`), else `/dashboard/`. Rate-limited at
`LOGIN_RATE_LIMIT` (default `20/m`) by client IP; over the limit returns a
`429` with a friendly message rather than actually authenticating.

## 5. Browsing the Curriculum

```
/dashboard/  →  /learn/<class>/  →  /learn/<class>/<subject>/  →  /learn/<class>/<subject>/<chapter>/<lesson>/
  (Class cards)   (Subject picker,       (Chapter accordion,          (Video + comments + resources +
                   skipped if the class    shows watched/quiz           prev/next navigation)
                   has exactly 1 subject)  status per chapter)
```

- Every level filters `is_active=True` — an admin can hide a class/subject
  from students without deleting it (and its lessons) from the database.
- `subject_list` auto-redirects straight to `chapter_list` when a class has
  exactly one active subject — no pointless one-card picker.
- `chapter_list` and `lesson_detail` compute watched/attempted state up
  front (`LessonProgress`, `QuizAttempt`) so templates can show checkmarks
  without per-row queries.
- Visiting `lesson_detail` always calls
  `LessonProgress.objects.get_or_create(user, lesson)` — a progress row
  exists for every lesson a student has ever opened, `watched=False` by
  default, independent of the explicit "mark as watched" action.

## 6. Marking a Lesson Watched

Student clicks "Mark as Watched" on `lesson_detail` → `fetch()` `POST` to
`/lesson/<id>/mark-watched/` with `X-CSRFToken` from the server-rendered
token → `progress.views.mark_watched` toggles `LessonProgress.watched` and
sets/clears `watched_at` → responds `{"watched": bool}` → the page updates
the button state without a reload. No page navigation occurs.

## 7. Student Dashboard Computation

On every `/dashboard/` load (`progress.views.dashboard`):
- One annotated query per visible `Class` (not one query per class) computes
  total lessons, watched lessons, and active subject count.
- Classes are grouped by their `CourseKind` (a hidden kind is treated as no
  kind — the heading disappears but its classes still show, each gated by
  its own `is_active`); classes with no kind (or a hidden kind) land in a
  trailing "ungrouped" section so a platform with zero kinds still renders
  exactly one section.
- **Study streak**: consecutive calendar days (up to today) with at least
  one `LessonProgress.watched_at` — yesterday still counts as "alive" so the
  streak doesn't reset before the day is over (`_study_streak`).
- **Resume lesson**: the first unwatched lesson in the chapter the student
  last watched something in, or that chapter's last lesson if everything in
  it is already watched (`_resume_target`).
- **Quizzes passed**: distinct count of `QuizAttempt.passed=True`, deduped
  per quiz (multiple passing retakes count once).

## 8. Taking a Quiz

1. `GET /quiz/<class>/<subject>/<chapter>/` → `quiz_view` renders all
   questions with their choices (prefetched).
2. `POST` with `question_<id>=<choice_id>` per question → server scores
   every question against `Choice.is_correct` (client never sees which
   choice is correct until after submitting).
3. A `QuizAttempt` row is created (score, total, `passed` = score% ≥
   `Quiz.pass_percentage`), plus one `QuizAnswer` row per question
   (`bulk_create`) recording exactly what was selected — this is what lets
   "View analysis" later reconstruct the same result screen without needing
   the original POST data.
4. **Every submission is a new `QuizAttempt`** — retakes are kept as
   history, not overwritten, so a student's improvement across attempts is
   visible (`admin_panel.views.student_report` shows the full list, not
   just the latest).
5. `GET /quiz/<class>/<subject>/<chapter>/analysis/` re-renders the
   most-recent attempt's result screen (`QuizAttempt.Meta.ordering =
   ['-attempted_at']`) by rebuilding the same result shape from stored
   `QuizAnswer` rows — no new submission needed.

## 9. Posting a Comment / Doubt

Handled inline inside `curriculum.views.lesson_detail` (see
[DECISIONS.md](DECISIONS.md) for why it's not a separate view) — a comment
always redirects back to the same lesson page either way:

1. `POST` to the lesson URL with `comment_body` (and optionally `parent_id`
   for a reply) present in the body.
2. Rate-limited 10/min per user (not per IP — the view is already
   `@login_required`). Over the limit: an error message, redirect back,
   nothing saved.
3. If `parent_id` is present, the parent comment is looked up **scoped to
   this lesson and to top-level comments only**
   (`get_object_or_404(Comment, id=parent_id, lesson=lesson, parent=None)`)
   — prevents attaching a reply under a comment from a different lesson, or
   nesting a reply under another reply (also enforced independently by
   `Comment.clean()`).
4. On success: comment saved, success message, redirect to the same lesson
   URL (`redirect(request.path)` — a POST-redirect-GET pattern that avoids
   duplicate submission on refresh).

## 10. Search

`GET /search/?q=...` (public — no `@login_required`) runs an `icontains`
match against name/title and description across `Class`, `Subject`,
`Chapter`, and `Lesson` simultaneously, each filtered to only
`is_active=True` rows (and their active ancestors) so hidden content can't
be discovered through search. Each of the four result sections paginates
independently with its own query param (`klpage`, `spage`, `cpage`,
`lpage`) so paging one section preserves the others' current page and the
search term.

## 11. Admin Content Authoring (the platform's core loop)

Everything a student sees originates here — a fresh database has zero rows
in the entire curriculum hierarchy. Staff use either `/panel/` (curated
CRUD, this project's own UI) or `/admin/` (Django Admin, full model access
with inlines — e.g. adding `Subject`s inline while editing a `Class`,
`Lesson`s inline while editing a `Chapter`).

Typical authoring order: `CourseKind` (optional) → `Class` → `Subject` →
`Chapter` → `Lesson` (YouTube video ID only — no file upload) → `Resource`
(optional PDF/doc attachments) → `Quiz` → `Question` → `Choice` (≥2 per
question, exactly one flagged `is_correct` by convention, not by DB
constraint).

`/panel/` specifics worth knowing:
- Blank slugs auto-fill from the name/title during form validation
  (`SlugFromNameMixin`), so a slug collision is caught as a normal form
  error, not a raw database `IntegrityError`.
- Deleting a `Resource` also deletes its underlying file from storage
  (`ResourceDeleteView.form_valid` explicitly calls `file.delete(save=False)`
  before the row is removed — deleting the row alone would leave an orphan
  file on disk).
- Adding a `Question` redirects straight to adding its `Choice`s
  (`QuestionCreateView.get_success_url` → `ap:choice_add`), not back to the
  quiz overview — matches the natural next step in authoring.
- `/panel/users/` lets staff search/list users and reach a read-only
  `student_report` (full quiz history + per-class watch progress) for any
  one student, plus the superuser-gated staff/active toggles described in
  [SECURITY.md](SECURITY.md).

## 12. Account Self-Service

`/account/` (edit first/last name + username), `/account/password/`
(Django's own change-password flow, session survives via
`update_session_auth_hash`), `/account/delete/` (re-enter password →
`User.delete()` → cascades to `GoogleAccount`, `LessonProgress`,
`QuizAttempt`, `Comment` automatically via `on_delete=CASCADE` — no signal
handling needed).
