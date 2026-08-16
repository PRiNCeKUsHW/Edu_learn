# AGENTS.md — EduLearn (Django E-Learning Platform)

Primary instruction file for AI coding agents working in this repository.
Read this first. It links out to specialized docs — don't re-derive what's
already written down there.

## Documentation Map

| Doc | Covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | App structure, request flow, auth flow, design decisions map |
| [DATABASE.md](DATABASE.md) | Models, relationships, constraints, migrations |
| [API.md](API.md) | URL routes, the one JSON endpoint, request/response shapes |
| [SECURITY.md](SECURITY.md) | Auth, authorization, CSRF, rate limiting, upload validation, known gaps |
| [WORKFLOWS.md](WORKFLOWS.md) | Registration/OAuth, watching a lesson, quiz attempts, admin content flows |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Setup, running locally, migrations, debugging |
| [TESTING.md](TESTING.md) | Test layout, how to run, what's covered |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Railway/Procfile deploy, env vars, static/media, logging |
| [DECISIONS.md](DECISIONS.md) | Why things are built the way they are — read before "improving" them |
| [README.md](README.md) | User-facing product README (setup + feature tour) |

## Project Overview

EduLearn is a server-rendered Django app for running an e-learning platform
where **the entire course hierarchy is admin-authored data, not code**.
Course Kind → Class → Subject → Chapter → Lesson is fully dynamic; an empty
database has none of these. YouTube videos are embedded by ID, quizzes are
MCQ, comments are single-level-threaded doubts per lesson.

There is no separate frontend build — templates render server-side with
Bootstrap 5. The only JSON/AJAX endpoint is `POST /lesson/<id>/mark-watched/`.

## Tech Stack

- **Backend:** Python, Django >=5.2 (see [requirements.txt](requirements.txt))
- **Frontend:** Django Templates + Bootstrap 5 (no JS framework, no build step)
- **Database:** SQLite by default; PostgreSQL via `DATABASE_URL` (`dj-database-url` + `psycopg`)
- **Auth:** Django's built-in `User`/session auth + a custom Google OAuth 2.0 flow
- **Rate limiting:** `django-ratelimit` backed by Django's `LocMemCache`
- **Static files:** WhiteNoise (no nginx/CDN in front in this deploy shape)
- **Prod server:** gunicorn (see [Procfile](Procfile))
- **Tests:** Django's built-in test runner (`manage.py test`); `freezegun` for time-sensitive rate-limit tests

## Repository Structure

```
elearn_project/            ← Django project root (this directory)
├── manage.py
├── requirements.txt
├── Procfile                # gunicorn start command for Railway-style deploy
├── .env                     # local env vars (gitignored)
├── db.sqlite3               # default local DB (gitignored)
│
├── elearn_project/          # Django project config package
│   ├── settings.py
│   ├── urls.py               # root URLconf — includes each app's urls.py
│   ├── logging_config.py     # ensure_log_dir() helper for prod file logging
│   ├── wsgi.py
│   └── tests.py              # settings-level tests (DATABASE_URL parsing, log dir)
│
├── accounts/                 # auth: login/logout, Google OAuth, account settings
├── curriculum/                # CourseKind/Class/Subject/Chapter/Lesson/Resource models + browsing views + search
├── progress/                   # LessonProgress model, dashboard view, mark-watched AJAX endpoint
├── quizzes/                     # Quiz/Question/Choice/QuizAttempt/QuizAnswer + quiz-taking views
├── discussions/                  # Comment model + CommentForm (posting itself happens in curriculum.views.lesson_detail)
├── admin_panel/                    # Staff-only CRUD UI at /panel/ — no models of its own, operates on the above apps' models
├── core/                             # Near-empty app; only real content is a `check_templates` management command
│
├── templates/                # Project-wide template DIRS root; one subfolder per app + base.html
├── static/                   # Project static source (css/js/images) — collected to staticfiles/ in prod
└── media/                    # User-uploaded files (thumbnails, resources) — gitignored
```

Each Django app under the project root is a **top-level package**, not
nested inside another — `accounts`, `curriculum`, `progress`, `quizzes`,
`discussions`, `admin_panel`, `core` all sit beside `manage.py`.

> **Note on README.md:** the README's "Project Structure" section describes
> an older single-`core`-app layout (`core/models.py`, `core/views.py`, etc.)
> that no longer matches reality — the code has since been split into the
> six apps above. Trust this file and the actual source tree over that one
> section of the README; the rest of the README (setup, Google OAuth, Postgres
> migration, feature tour) is accurate.

## Development Commands

```bash
# from elearn_project/ (this directory), with venv active
python manage.py runserver          # dev server → http://127.0.0.1:8000
python manage.py migrate            # apply migrations
python manage.py makemigrations     # after changing any models.py
python manage.py createsuperuser    # for /admin/ and /panel/ access
python manage.py test               # full test suite
python manage.py test accounts      # one app's tests
python manage.py check_templates    # custom command: flags Django template tags split across lines
python manage.py collectstatic      # only needed to reproduce the prod static pipeline locally
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for full setup and [TESTING.md](TESTING.md)
for test structure. There is **no linter/formatter/CI config** in this repo
(no `.flake8`, `pyproject.toml`, `pytest.ini`, or `.github/workflows/`) — do
not invent commands for these.

## Where Code Belongs

| Kind of change | Goes in |
|---|---|
| Course hierarchy fields/rules (Class, Subject, Chapter, Lesson, Resource) | `curriculum/models.py` |
| Student browsing/search pages | `curriculum/views.py`, `curriculum/urls.py` |
| Watched/progress tracking, student dashboard | `progress/models.py`, `progress/views.py` |
| Quiz data model or quiz-taking logic | `quizzes/models.py`, `quizzes/views.py` |
| Comment/doubt model or form | `discussions/models.py`, `discussions/forms.py` (posting logic lives in `curriculum/views.py:lesson_detail`, see [DECISIONS.md](DECISIONS.md)) |
| Login, registration, Google OAuth, account settings | `accounts/` |
| Staff CRUD UI (`/panel/...`) | `admin_panel/` — forms in `forms.py`, shared CBV plumbing in `mixins.py` |
| Django Admin (`/admin/...`) customization | each app's own `admin.py` |
| Cross-cutting settings, logging, root URLconf | `elearn_project/` |
| One-off management commands | `core/management/commands/` |
| Templates | `templates/<app_name>/...`, layout in `templates/base.html` |
| Static CSS/JS/images | `static/css`, `static/js`, `static/images` |

## Architecture Rules — Read Before Changing Structure

- **Don't add a custom user model.** `GoogleAccount` deliberately extends the
  stock `django.contrib.auth.User` via `OneToOneField` rather than swapping
  `AUTH_USER_MODEL` — every FK in `progress`, `quizzes`, `discussions`, and
  the whole admin panel already points at `User`. See [DECISIONS.md](DECISIONS.md).
- **`admin_panel` has no models of its own.** It's a staff-facing CRUD UI
  over `curriculum`, `quizzes`, and `discussions` models. New staff-manageable
  content types belong in their domain app's `models.py`, with the CRUD
  views/forms added to `admin_panel`.
- **The Class → Subject → Chapter → Lesson hierarchy carries no hardcoded
  domain assumptions.** Don't add special-cased logic for "a school" or
  "a class number" — every level is admin-authored data. See the README's
  "Building a Different Kind of Platform" section.
- **`Chapter.slug` and `Lesson.slug` are only unique within their parent**
  (`unique_together`), not globally. Always resolve them scoped through
  their parent chain (see `curriculum.views._get_subject` and how
  `quizzes.views.quiz_view` reuses it) — a bare slug-only lookup can raise
  `MultipleObjectsReturned`.
- **Comment posting is intentionally inline in `curriculum.views.lesson_detail`**,
  not a separate `discussions` view — don't "clean this up" into its own
  endpoint; it changes the POST target and was a deliberate choice (see
  [DECISIONS.md](DECISIONS.md)).
- **Two separate staff surfaces exist on purpose:** Django Admin (`/admin/`,
  full model access, `is_staff` gate via Django itself) and the custom panel
  (`/panel/`, curated CRUD UI, `staff_member_required`). Don't merge them.

## Security Rules

Full detail in [SECURITY.md](SECURITY.md). The essentials:

- Never commit real values into `.env` — it's already gitignored; only
  placeholder/example values belong in anything committed.
- `GOOGLE_OAUTH_CLIENT_SECRET` is used **only** in `accounts/google_oauth.py`
  server-side token exchange. Never expose it to a template or static JS file.
- Any new file upload field must go through `FileExtensionValidator` with an
  explicit allow-list (see `curriculum.models.ALLOWED_RESOURCE_EXTENSIONS`)
  plus a size validator — never accept `.html`/`.svg`/`.js` uploads served
  from `/media/` (same-origin execution risk).
- Any new POST-handling view that's cheap to spam (creates a row, sends an
  email, etc.) should use `django_ratelimit.decorators.ratelimit` the same
  way `accounts/views.py` and `curriculum/views.py:lesson_detail` do —
  `key='user'` for `@login_required` views, `key='ip'` for anonymous ones
  (via `accounts.ratelimit.get_client_ip`, not raw `REMOTE_ADDR`).
- Privilege-escalating actions (granting `is_staff`, deactivating a staff/admin
  account) must stay `is_superuser`-gated — see
  `admin_panel.views.user_toggle_staff` / `user_toggle_active` for the pattern.
- Don't derive `GOOGLE_OAUTH_REDIRECT_URI` from the incoming request — it
  must stay a fixed, explicitly configured value.

## Testing Requirements

- Every app with behavior has a `tests/` package (or `tests.py`) — see
  [TESTING.md](TESTING.md) for the full map. Add new tests alongside the
  existing ones in the owning app, not in `elearn_project/tests.py` (that
  file is reserved for settings-level tests that don't need a request cycle).
- Run `python manage.py test` before considering a change done. For changes
  touching rate-limited views, check whether `freezegun` is needed to avoid
  a window-boundary flake (see existing rate-limit tests for the pattern).
- `admin_panel/tests.py` is the single largest test file (630 lines) — skim
  it before changing any CRUD view or mixin in that app; it locks in a lot
  of behavior (staff gates, slug autofill, file cleanup on delete, superuser
  guards).

## Migration Rules

- Run `makemigrations <app>` immediately after any `models.py` change, and
  commit the generated migration file alongside the model change — never
  hand-edit an already-applied migration.
- This project runs on both SQLite (dev default) and PostgreSQL (prod, via
  `DATABASE_URL`) — avoid raw SQL or backend-specific field options in
  migrations; stick to plain Django ORM so both backends keep working.
  See [DATABASE.md](DATABASE.md) and the README's "Migrating to PostgreSQL"
  section.

## API / URL Modification Rules

- This is not a REST API — routes render HTML except the one JSON endpoint
  (`mark_watched`). See [API.md](API.md) for the full route table before
  adding, renaming, or moving a URL.
- `Chapter`/`Lesson` routes are scoped `class_slug/subject_slug/chapter_slug/...`
  precisely because their slugs aren't globally unique — never shortcut a
  new route to skip the parent segments.
- Adding an `admin_panel` route means adding it under the `ap:` namespace in
  `admin_panel/urls.py` and following the existing `AdminListMixin` /
  `AdminFormMixin` / `AdminDeleteMixin` pattern from `admin_panel/mixins.py`
  rather than writing a bespoke function view.

## Frontend/Backend Separation

There is no API boundary to preserve — views render Django templates
directly, and templates live under `templates/<app>/`. The one exception is
`mark_watched`, which returns `JsonResponse({'watched': bool})` and is
called via `fetch()` from `templates/curriculum/lesson_detail.html`,
authenticated by the server-rendered `{{ csrf_token }}` (never
`document.cookie` — `CSRF_COOKIE_HTTPONLY` is `True`). Keep any new AJAX
endpoint consistent with that pattern.

## Things an AI Agent MUST NOT Do

- Do not swap `AUTH_USER_MODEL` or add a custom user model.
- Do not commit `.env`, `db.sqlite3`, `media/`, or anything under `logs/`.
- Do not hand-edit an applied migration file; generate a new one instead.
- Do not weaken `CSRF_COOKIE_HTTPONLY`, `SESSION_COOKIE_HTTPONLY`, or the
  file-upload extension allow-list without a documented reason (see
  [SECURITY.md](SECURITY.md) for why each exists).
- Do not derive `GOOGLE_OAUTH_REDIRECT_URI` from `request` at runtime.
- Do not add hardcoded domain assumptions ("a school has terms", "a class
  has grades") into the curriculum hierarchy — it must stay fully
  admin-authored.
- Do not invent CI/lint/format commands — none exist in this repo.

## Things an AI Agent SHOULD Always Do Before Making Changes

- Read [ARCHITECTURE.md](ARCHITECTURE.md) and the relevant app's existing
  `models.py`/`views.py` before adding a feature — most cross-cutting
  concerns (slug scoping, rate limiting, staff gating) already have an
  established pattern elsewhere in the codebase; follow it rather than
  reinventing it.
- Check [DECISIONS.md](DECISIONS.md) before "simplifying" something that
  looks odd — a lot of this codebase's non-obvious choices are deliberate
  and explained in code comments (X-Real-IP vs X-Forwarded-For, CSRF cookie
  settings, rate-limit sizing, etc.).
- Run `python manage.py test` (and `python manage.py check_templates` for
  template edits) before calling a change complete.
