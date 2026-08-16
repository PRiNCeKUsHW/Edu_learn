# DEVELOPMENT.md

How to set up and work on this project locally. See [DEPLOYMENT.md](DEPLOYMENT.md)
for production; [TESTING.md](TESTING.md) for the test suite in depth.

## Prerequisites

- Python 3.10+ (per README.md; Django itself requires `>=5.2` per
  `requirements.txt`, which needs Python 3.10+).
- No Node/JS toolchain needed — templates are server-rendered, no frontend
  build step.

## Setup

```bash
cd elearn_project        # this directory — contains manage.py

python -m venv venv
venv\Scripts\activate     # Windows
# source venv/bin/activate  # macOS/Linux

pip install -r requirements.txt
```

## Environment Configuration

Managed via `python-decouple`, read from `.env` in this directory
(gitignored — never commit real values). A `.env` with development
defaults already exists in a fresh checkout. Variables (see
[SECURITY.md](SECURITY.md#secrets--environment-variables) for what each
does):

- `SECRET_KEY`, `DEBUG` — always set for local dev; the placeholder
  `SECRET_KEY` is fine as long as `DEBUG=True` (the app refuses to boot with
  the placeholder once `DEBUG=False`).
- `GOOGLE_OAUTH_CLIENT_ID` / `_CLIENT_SECRET` / `_REDIRECT_URI` — optional;
  leave unset to develop without Google sign-in (the button just won't
  appear). See README.md's "Google Sign-In setup" for how to obtain real
  values from Google Cloud Console if you need to test that flow.
- `DATABASE_URL` — leave unset for the zero-config SQLite default.
- `ALLOWED_HOSTS`, `LOGIN_RATE_LIMIT`, `REGISTRATION_RATE_LIMIT` — have
  working defaults; only touch these if you're specifically testing that
  behavior.

## Database Setup

```bash
python manage.py migrate          # creates db.sqlite3 on first run
python manage.py createsuperuser  # for /admin/ and /panel/ access
```

No seed data / fixtures exist — a fresh database has zero content rows by
design. Populate it through `/panel/` or `/admin/` after creating a
superuser (see [WORKFLOWS.md](WORKFLOWS.md#11-admin-content-authoring-the-platforms-core-loop)).

To reset the local DB, delete `db.sqlite3` and re-run `migrate`.

## Running Locally

```bash
python manage.py runserver
```

Visit `http://127.0.0.1:8000` (landing page), `http://127.0.0.1:8000/admin/`
(Django Admin), `http://127.0.0.1:8000/panel/` (custom staff panel — needs
`is_staff`).

A `.claude/launch.json` entry (`elearn-dev-8000`) also starts this same
command on port 8000 for editor-integrated preview tooling.

## Making Model Changes

```bash
# after editing any app's models.py
python manage.py makemigrations <app_name>
python manage.py migrate
```

Commit the generated migration file with the model change. Keep migrations
backend-agnostic (plain ORM, no raw SQL) — this project runs on both SQLite
and PostgreSQL; see [DATABASE.md](DATABASE.md).

## Testing

```bash
python manage.py test              # full suite
python manage.py test accounts     # one app
python manage.py test accounts.tests.test_auth   # one module
```

See [TESTING.md](TESTING.md) for structure, coverage, and the `freezegun`
pattern used for rate-limit tests.

## Template Linting

```bash
python manage.py check_templates
```

Custom management command (`core/management/commands/check_templates.py`)
that compiles every template and flags any Django tag (`{{ }}`, `{% %}`,
`{# #}`) that got split across lines by an HTML formatter — Django's tag
lexer requires a tag to open and close on the same line; a `{% %}` split
raises at render time, a `{{ }}` split silently renders as literal text
instead of failing loudly. Run this after any template edit made by a tool
that isn't Django-template-aware.

The repo also ships editor config to prevent this in the first place:
`.vscode/settings.json` disables VS Code's built-in HTML formatter on
`templates/**/*.html`, and `.prettierignore` excludes the same paths from
Prettier. If you're editing templates with a different tool, be aware it
may not respect either of these.

## Formatting / Linting

**None configured.** No `.flake8`, `pyproject.toml`, `ruff.toml`, or
`setup.cfg` exists in this repo, and no CI runs any such check. Don't
introduce a new formatter's opinions into a diff unless asked to add one
project-wide.

## Debugging

- With `DEBUG=True`, Django's own debug error pages are active (full
  tracebacks, no custom 404/500 templates exist).
- Console logging is always on; see `elearn_project/settings.py`'s
  `LOGGING` config. In dev, only the `console` handler is wired (file
  handlers are only added when `DEBUG=False` — see
  `elearn_project/logging_config.py`).
- Project loggers you can raise/lower verbosity on via `DJANGO_LOG_LEVEL`:
  `core`, `accounts`, `curriculum`, `progress`, `admin_panel` (each logs
  through `logging.getLogger(__name__)` in its `views.py`).

## Common Problems

- **Google sign-in button missing locally** — expected unless all three
  `GOOGLE_OAUTH_*` env vars are set; not a bug.
- **Template edit silently not rendering / raising `TemplateSyntaxError`**
  — run `python manage.py check_templates`; almost always a tag split
  across lines by an auto-formatter.
- **`MultipleObjectsReturned` on a chapter/lesson/quiz lookup** — a bare
  slug-only query was used instead of scoping through the full
  `Class → Subject → Chapter` chain; `Chapter.slug`/`Lesson.slug` are only
  unique within their parent (see [DATABASE.md](DATABASE.md)).
- **Rate-limit test flakes intermittently** — likely missing `freezegun`;
  `django-ratelimit` windows by real epoch time, so a burst of test
  requests straddling a window boundary can occasionally get an unexpected
  count. See existing tests in `accounts/tests/` for the pattern.

## Build / Deployment Preparation

No separate "build" step for this app locally (see
[DEPLOYMENT.md](DEPLOYMENT.md) for what production actually runs —
`collectstatic`, `migrate`, then `gunicorn`). To reproduce the production
static-file pipeline locally:

```bash
python manage.py collectstatic
```
