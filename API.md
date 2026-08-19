# API.md

This is a server-rendered Django app, not a REST/JSON API service. Nearly
every route returns full HTML. This file documents the complete route
table and the one genuine JSON endpoint.

## Architecture

- No API versioning, no DRF, no separate API app.
- No pagination/filtering query-param convention beyond what's described
  per-route below (search and admin list views use plain `?page=`).
- "Authorization requirement" below means the Django-level gate applied to
  the view — see [SECURITY.md](SECURITY.md) for what each tier can do.
- All POST-handling routes are CSRF-protected by Django's
  `CsrfViewMiddleware` (project-wide, not opt-in per view).

## The One JSON Endpoint

### `POST /lesson/<int:lesson_id>/mark-watched/` — `mark_watched`

- **Auth:** `@login_required`, `@require_POST`.
- **App/view:** `progress.views.mark_watched`.
- **Request:** no body needed; CSRF token via `X-CSRFToken` header, sourced
  from the server-rendered `{{ csrf_token }}` template variable (never read
  from `document.cookie` — see [SECURITY.md](SECURITY.md)).
- **Behavior:** toggles `LessonProgress.watched` for
  `(request.user, lesson)`, creating the row if it doesn't exist. Sets/clears
  `watched_at` accordingly.
- **Response:** `200 application/json` — `{"watched": true | false}`.
- **Errors:** `404` if the lesson doesn't exist; `405` if not POST; a
  redirect to login if unauthenticated.
- Called from `templates/curriculum/lesson_detail.html` via `fetch()`.

## Full Route Table

### `accounts` (mounted at project root)

| Method | Path | View | Name | Auth |
|---|---|---|---|---|
| GET | `/` | `landing` | `landing` | public (redirects to dashboard if logged in) |
| GET | `/register/` | `register_view` | `register` | public — Google-only signup entry point |
| GET/POST | `/login/` | `login_view` | `login` | public; rate-limited (`LOGIN_RATE_LIMIT`, key=ip) |
| POST | `/logout/` | `logout_view` | `logout` | any; `@require_POST` + CSRF — a GET logout could be fired by a prefetch or an `<img>` tag |
| GET | `/accounts/google/login/` | `google_login_view` | `google_login` | public |
| GET | `/accounts/google/callback/` | `google_callback_view` | `google_callback` | public; rate-limited (key=ip) |
| GET/POST | `/accounts/google/complete-profile/` | `google_complete_profile_view` | `google_complete_profile` | requires valid `pending_google` session; rate-limited (`REGISTRATION_RATE_LIMIT`) |
| GET/POST | `/accounts/google/link/` | `google_link_confirm_view` | `google_link_confirm` | requires valid pending session; rate-limited |
| GET/POST | `/account/` | `account_settings_view` | `account_settings` | `@login_required` |
| GET/POST | `/account/password/` | `AccountPasswordChangeView` | `account_password_change` | `@login_required` (Django's `PasswordChangeView`) |
| GET/POST | `/account/delete/` | `account_delete_view` | `account_delete` | `@login_required`; requires re-entering current password |

### `curriculum` (mounted at project root)

| Method | Path | View | Name | Auth |
|---|---|---|---|---|
| GET | `/search/` | `search_view` | `search` | public (no `@login_required`) |
| GET | `/learn/<slug:class_slug>/` | `subject_list` | `subject_list` | `@login_required` |
| GET | `/learn/<slug:class_slug>/<slug:subject_slug>/` | `chapter_list` | `chapter_list` | `@login_required` |
| GET/POST | `/learn/<class_slug>/<subject_slug>/<chapter_slug>/<lesson_slug>/` | `lesson_detail` | `lesson_detail` | `@login_required`; POST branch (comment post) rate-limited 10/min, key=user |

### `progress` (mounted at project root)

| Method | Path | View | Name | Auth |
|---|---|---|---|---|
| GET | `/dashboard/` | `dashboard` | `dashboard` | `@login_required` |
| GET | `/my-progress/` | `my_progress` | `my_progress` | `@login_required`; the student's own report card — per-class completion, quiz marks, study time |
| POST | `/lesson/<int:lesson_id>/mark-watched/` | `mark_watched` | `mark_watched` | `@login_required`, JSON — see above |

### `quizzes` (mounted at project root)

| Method | Path | View | Name | Auth |
|---|---|---|---|---|
| GET/POST | `/quiz/<class_slug>/<subject_slug>/<chapter_slug>/` | `quiz_view` | `quiz` | `@login_required`; POST scores + records a `QuizAttempt` |
| GET | `/quiz/<class_slug>/<subject_slug>/<chapter_slug>/analysis/` | `quiz_analysis_view` | `quiz_analysis` | `@login_required`; re-renders the most recent attempt, or the one named by `?attempt=<id>` (scoped to the requesting user, so another student's id 404s) |

### `admin_panel` (mounted at `/panel/`, namespace `ap`)

All routes below are `staff_member_required` (redirects to `/admin/login/`
if not staff), built on `admin_panel.mixins` CBV mixins unless noted.

| Method | Path | View | Name |
|---|---|---|---|
| GET | `/panel/` | `dashboard` | `ap:dashboard` |
| GET | `/panel/kinds/` | `CourseKindListView` | `ap:coursekind_list` |
| GET/POST | `/panel/kinds/add/` | `CourseKindCreateView` | `ap:coursekind_add` |
| GET/POST | `/panel/kinds/<pk>/edit/` | `CourseKindUpdateView` | `ap:coursekind_edit` |
| GET/POST | `/panel/kinds/<pk>/delete/` | `CourseKindDeleteView` | `ap:coursekind_delete` |
| GET | `/panel/classes/` | `ClassListView` (filterable `?kind=`) | `ap:class_list` |
| GET/POST | `/panel/classes/add/` | `ClassCreateView` | `ap:class_add` |
| GET/POST | `/panel/classes/<pk>/edit/` | `ClassUpdateView` | `ap:class_edit` |
| GET/POST | `/panel/classes/<pk>/delete/` | `ClassDeleteView` | `ap:class_delete` |
| GET | `/panel/subjects/` | `SubjectListView` (filterable `?class=`) | `ap:subject_list` |
| GET/POST | `/panel/subjects/add/` | `SubjectCreateView` | `ap:subject_add` |
| GET/POST | `/panel/subjects/<pk>/edit/` | `SubjectUpdateView` | `ap:subject_edit` |
| GET/POST | `/panel/subjects/<pk>/delete/` | `SubjectDeleteView` | `ap:subject_delete` |
| GET | `/panel/chapters/` | `ChapterListView` (filterable `?class=&subject=`) | `ap:chapter_list` |
| GET/POST | `/panel/chapters/add/` | `ChapterCreateView` | `ap:chapter_add` |
| GET/POST | `/panel/chapters/<pk>/edit/` | `ChapterUpdateView` | `ap:chapter_edit` |
| GET/POST | `/panel/chapters/<pk>/delete/` | `ChapterDeleteView` | `ap:chapter_delete` |
| GET | `/panel/lessons/` | `LessonListView` (filterable `?class=`, searchable `?q=`) | `ap:lesson_list` |
| GET/POST | `/panel/lessons/add/` | `LessonCreateView` | `ap:lesson_add` |
| GET/POST | `/panel/lessons/<pk>/edit/` | `LessonUpdateView` | `ap:lesson_edit` |
| GET/POST | `/panel/lessons/<pk>/delete/` | `LessonDeleteView` | `ap:lesson_delete` |
| GET | `/panel/resources/` | `ResourceListView` | `ap:resource_list` |
| GET/POST | `/panel/resources/add/` | `ResourceCreateView` | `ap:resource_add` |
| GET/POST | `/panel/resources/<pk>/delete/` | `ResourceDeleteView` (also deletes the underlying file from storage) | `ap:resource_delete` |
| GET | `/panel/quizzes/` | `QuizListView` | `ap:quiz_list` |
| GET/POST | `/panel/quizzes/add/` | `QuizCreateView` | `ap:quiz_add` |
| GET | `/panel/quizzes/<pk>/` | `quiz_detail` (function view) | `ap:quiz_detail` |
| GET/POST | `/panel/quizzes/<pk>/edit/` | `QuizUpdateView` | `ap:quiz_edit` |
| GET/POST | `/panel/quizzes/<pk>/delete/` | `QuizDeleteView` | `ap:quiz_delete` |
| GET/POST | `/panel/quizzes/<quiz_pk>/questions/add/` | `QuestionCreateView` | `ap:question_add` |
| GET/POST | `/panel/questions/<pk>/edit/` | `QuestionUpdateView` | `ap:question_edit` |
| GET/POST | `/panel/questions/<pk>/delete/` | `QuestionDeleteView` | `ap:question_delete` |
| GET/POST | `/panel/questions/<question_pk>/choices/` | `ChoiceCreateView` | `ap:choice_add` |
| GET/POST | `/panel/choices/<pk>/delete/` | `ChoiceDeleteView` | `ap:choice_delete` |
| GET | `/panel/users/` | `UserListView` (searchable `?q=`) | `ap:user_list` |
| GET | `/panel/users/<pk>/report/` | `student_report` (function view) | `ap:user_report` |
| POST | `/panel/users/<pk>/toggle-staff/` | `user_toggle_staff` — **`is_superuser`-only** | `ap:user_toggle_staff` |
| POST | `/panel/users/<pk>/toggle-active/` | `user_toggle_active` — superuser-only if target is staff/superuser | `ap:user_toggle_active` |
| GET | `/panel/comments/` | `CommentListView` | `ap:comment_list` |
| POST | `/panel/comments/<pk>/delete/` | `comment_delete` (function view) | `ap:comment_delete` |

### Django Admin & static/media (dev only)

- `/admin/...` — full Django Admin, `is_staff` gate (per-model
  `has_*_permission`), configured per-app in each `admin.py`.
- `/media/...`, `/static/...` — served by Django's dev-only `static()`
  helper **only when `DEBUG=True`**; in production WhiteNoise serves
  `/static/` and a real storage backend/proxy must serve `/media/` (see
  [DEPLOYMENT.md](DEPLOYMENT.md)).

## Request/Response Conventions

- **Forms:** standard Django `ModelForm`/`Form` — server-side validation
  errors re-render the same template with `form.errors`; no client-side
  validation framework beyond HTML5 `required`/`type` attributes.
- **Errors:** no custom error JSON shape — validation failures re-render
  HTML forms; `404`/`403`/`500` use Django's default error handling
  (custom templates only if added under `templates/`, none exist currently).
- **Redirects:** `messages` framework (`django.contrib.messages`) is used
  throughout for one-shot success/error banners shown after a redirect.
- **Pagination:** admin_panel list views use Django's `ListView.paginate_by
  = 25` (see `AdminListMixin`); `curriculum.search_view` paginates each of
  its four result sections independently (10/page) with separate query
  params (`klpage`, `spage`, `cpage`, `lpage`) so paging one section doesn't
  reset another.
- **Sorting/filtering:** ad hoc per view via `request.GET` (e.g.
  `?kind=`, `?class=`, `?subject=`, `?q=`) — no shared filtering
  convention/library.
