# DEPLOYMENT.md

Describes the deployment shape this project is actually built for, per
`Procfile`, `requirements.txt`, and `elearn_project/settings.py`. No
credentials are included below.

## Hosting Platform

Built for a **Railway-style single-process deploy** (Railway is named
explicitly in code comments throughout `settings.py` and README.md), but
nothing is Railway-specific at the code level beyond the client-IP header
choice in `accounts/ratelimit.py` — any platform that runs a `Procfile`-style
start command (Heroku, Render, Fly.io, a bare VM) works the same way.

There is **no `.github/workflows/`, no `Dockerfile`, no `railway.json`, no
CI/CD configuration** in this repo. Deployment is whatever the hosting
platform does with `Procfile` + `requirements.txt` — there is no automated
pipeline to describe beyond that.

## Production Architecture

```
Internet → TLS-terminating proxy (platform-managed) → gunicorn (3 workers) → Django (WhiteNoise serves /static/ inline) → PostgreSQL (via DATABASE_URL) or SQLite file
```

- **App server:** `gunicorn`, 3 workers, binding `0.0.0.0:$PORT` (see
  `Procfile`).
- **Static files:** served **by the app process itself** via WhiteNoise
  middleware (`whitenoise.middleware.WhiteNoiseMiddleware`, placed right
  after `SecurityMiddleware` per WhiteNoise's own requirement) — there is
  no nginx/CDN in front. Without this, `DEBUG=False` means zero CSS/JS/icons
  (Django's own dev-only `static()` helper is explicitly gated off outside
  `DEBUG` in `elearn_project/urls.py`).
- **Media files** (`/media/...` — thumbnails, resources): in `DEBUG=True`
  only, Django's dev `static()` helper serves them. **In production, no
  code in this repo serves `/media/`** — that requires the web server or a
  storage backend in front, per the comment in `elearn_project/urls.py`.
  This is a **gap to solve at deploy time**, not something already handled.
- **Database:** PostgreSQL via `DATABASE_URL` (recommended for real
  concurrent traffic) or the same zero-config SQLite file used in dev (fine
  only for small/low-concurrency deployments). See
  [DATABASE.md](DATABASE.md) and README.md's "Migrating to PostgreSQL".

## Build Process

```
web: python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn elearn_project.wsgi --bind 0.0.0.0:$PORT --workers 3
```

(exact contents of `Procfile`) — migrations run automatically on every
deploy, before `collectstatic`, before the app server starts. There is no
separate manual migration step in this deploy shape; a broken migration
blocks the deploy from ever serving traffic.

`STORAGES['staticfiles']` switches to
`whitenoise.storage.CompressedManifestStaticFilesStorage` (compressed,
cache-busted/hashed filenames) whenever `DEBUG=False` — this backend
requires `collectstatic` to have already run and fails hard on a missing
file, which is why it's dev-gated (`StaticFilesStorage` in dev has none of
that friction).

## Environment Variables

See [SECURITY.md](SECURITY.md#secrets--environment-variables) for the full
table and what each one does. At minimum for a production boot:

- `SECRET_KEY` — must be a real generated value; the app **refuses to
  start** if `DEBUG=False` and this is still the `django-insecure-...`
  placeholder.
- `DEBUG=False`
- `ALLOWED_HOSTS` — the real domain(s), comma-separated.
- `DATABASE_URL` — if using PostgreSQL (recommended).
- `CSRF_TRUSTED_ORIGINS` — the real `https://...` origin(s) that will POST
  to this app.
- `GOOGLE_OAUTH_CLIENT_ID` / `_CLIENT_SECRET` / `_REDIRECT_URI` — only if
  Google sign-in should be live; `GOOGLE_OAUTH_REDIRECT_URI` must exactly
  match a redirect URI registered on the Google OAuth client (scheme, host,
  port, trailing slash) — see README.md's Google Sign-In setup section.
- Optional tuning: `SECURE_SSL_REDIRECT` (default `True`),
  `SECURE_HSTS_SECONDS` (default `3600` — start low, raise once TLS is
  confirmed stable; browsers honor `max-age` even after the header stops
  being sent), `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `LOGIN_RATE_LIMIT`,
  `REGISTRATION_RATE_LIMIT`, `DJANGO_LOG_LEVEL`.

Never place real values for any of these in a committed file.

## Static & Media Files in Production

- **Static** (`STATIC_ROOT = staticfiles/`): populated by `collectstatic`
  (already wired into `Procfile`), served by WhiteNoise. No action needed
  beyond correct env vars.
- **Media** (`MEDIA_ROOT = media/`): **not served by any code path when
  `DEBUG=False`.** Before relying on `Resource` file uploads or `Class`
  thumbnails in production, put a real storage backend (a proxy rule, a
  cloud storage service via a package like `django-storages`, etc.) in
  front of `/media/` — this is currently undocumented-as-solved and should
  be treated as an open deployment task, not an existing feature.
- Both `media/` and a locally mounted `logs/` directory are **ephemeral**
  on a typical container host (Railway included) unless explicitly mounted
  as a persistent Volume — anything written there is wiped on redeploy.

## Database Migrations in Deployment

Run automatically as the first step of every deploy (`migrate --noinput` in
`Procfile`), before the app starts serving. There is no separate rollback
tooling — reverting a bad migration in production means writing and
deploying a new migration that undoes it (or restoring a DB backup), the
same as any standard Django project.

## Logging in Production

- Outside `DEBUG`, the app writes to `logs/edulearn.log` (general),
  `logs/errors.log` (ERROR+), and `logs/security.log` (WARNING+, kept
  longest — 10 rotated backups vs. 5 for the others, as the audit trail),
  **in addition to console output**, gated by
  `elearn_project/logging_config.py:ensure_log_dir()`.
- If the log directory can't be created (read-only filesystem, permissions
  problem, full disk), the app **degrades to console-only logging rather
  than crashing at import time** — this is a deliberate fallback, not a bug
  to fix.
- **Console output is the durable record on a host like Railway** — it's
  what the platform's own Logs tab captures, and it survives redeploys
  independent of the app's filesystem. The local rotating files are a
  same-box, between-restarts convenience for `tail`-ing in a shell on the
  box — not a substitute for the platform's own log view, and not durable
  unless `logs/` is mounted as a persistent Volume.
- `RotatingFileHandler` is pinned to UTF-8 explicitly (not the OS locale
  default) — otherwise the em-dash used in the `verbose` log formatter (and
  any other non-ASCII content) gets mangled on a Windows host's default
  locale.

## Health Checks

**None configured in this repo** — no `/health/` or `/healthz/` endpoint,
no platform health-check config file. If the hosting platform requires one,
it needs to be added (e.g. a trivial view returning `200`); nothing today
serves that purpose.

## Rollback Considerations

- No blue/green or automated rollback tooling in this repo — rollback is
  whatever the hosting platform provides for reverting to a previous
  deploy/build.
- Because `migrate` runs automatically on every deploy, rolling back the
  *code* to a previous version while the *database* has already migrated
  forward can leave the app querying for columns/tables the old code
  doesn't expect — plan schema changes to be backward-compatible for at
  least one deploy when a rollback is a realistic possibility.
- `CACHES` is `LocMemCache` (in-memory, per-process) — a redeploy or
  rollback loses all rate-limit counters with it; not persisted, not worth
  worrying about in a rollback.
