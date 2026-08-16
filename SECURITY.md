# SECURITY.md

Describes the CURRENT security implementation only. No secrets are included
below — only variable names and mechanisms.

## Authentication

**Implemented:**
- Django's built-in session-based auth (`django.contrib.auth`) for
  username/password login (`accounts.views.login_view`,
  `AuthenticationForm`).
- Google OAuth 2.0 server-side "authorization code" flow
  (`accounts/google_oauth.py`, `accounts/views.py`) as an alternative
  sign-in/sign-up method. **New account creation is Google-only** —
  `/register/` has no password form.
- Passwords are hashed by Django's default password hasher (PBKDF2); never
  stored or logged in plaintext.
- `AUTH_PASSWORD_VALIDATORS` enabled: `UserAttributeSimilarityValidator`,
  `MinimumLengthValidator`, `CommonPasswordValidator`,
  `NumericPasswordValidator` (Django defaults, in `settings.py`).
- Google ID token verification (`google-auth` library): signature checked
  against Google's public keys, plus expiry, issuer, and
  `audience=GOOGLE_OAUTH_CLIENT_ID` — a token minted for a different app
  can't be replayed here. `email_verified` claim is explicitly checked;
  unverified emails are rejected.
- OAuth CSRF protection: a random `state` (`secrets.token_urlsafe(32)`)
  is stored in the session before redirecting to Google and compared with
  `secrets.compare_digest` on callback (constant-time comparison).
- `GOOGLE_OAUTH_REDIRECT_URI` is a fixed, explicitly configured value —
  never derived from the incoming request's `Host` header, so a forged
  `Host` header cannot redirect the OAuth flow.
- Login redirect (`?next=`) is validated with
  `url_has_allowed_host_and_scheme` before being followed — blocks
  open-redirect via a crafted login link.
- Account deletion requires re-entering the current password
  (`account_delete_view`) — guards against deleting an account from an
  unattended, already-logged-in session.

**Not implemented:**
- No multi-factor authentication.
- No email verification step for password-based signup — moot in practice
  since password-based *signup* doesn't exist; only Google-verified emails
  create new accounts. Existing password accounts predate this constraint.
- No "forgot password" / password-reset-by-email flow visible in the routes
  (`accounts/urls.py` has no `password_reset` path).
- No account lockout after repeated failed logins beyond the rate limit
  (see below) — rate limiting throttles, it doesn't lock.

## Authorization

Three tiers, checked per-view (no general permissions/roles framework):

| Tier | Mechanism |
|---|---|
| Anonymous | default |
| Authenticated | `@login_required` decorator |
| Staff | `staff_member_required` (function views) / `StaffRequiredMixin` (class-based views in `admin_panel`) |
| Superuser | explicit `if not request.user.is_superuser:` checks inside specific views |

**Privilege-escalation guards** (`admin_panel/views.py`):
- `user_toggle_staff` — only a superuser can grant/revoke `is_staff`. A
  staff-only gate here would let a compromised staff account mint more
  staff accounts. A user can't change their own staff status, and a
  superuser's staff status can't be changed at all through this route.
- `user_toggle_active` — a user can't deactivate themself. Deactivating a
  staff/superuser account requires `is_superuser` (deactivating an admin is
  itself an escalation vector — it can lock out the people who could undo
  the change).
- Both log a `logger.warning` when a non-superuser attempts the
  superuser-only action.
- `GoogleAccountAdmin` (Django Admin) has `has_add_permission` returning
  `False` and all fields `readonly` — this row is only ever created through
  the verified OAuth flow, never hand-edited.

**Not implemented:**
- No per-object permissions (e.g. "only the comment's author can edit it" —
  comments currently have no edit route at all; deletion is staff-only via
  `admin_panel`).
- No group-based permissions (`django.contrib.auth.Group` unused).

## Password Handling

- Never logged, never stored in plaintext.
- `AccountPasswordChangeView` is a thin wrapper around Django's own
  `PasswordChangeView` — validates the old password, enforces
  `AUTH_PASSWORD_VALIDATORS`, and calls `update_session_auth_hash` so the
  current session survives the change (no forced re-login).
- `GoogleCompleteProfileForm` extends `UserCreationForm` unchanged for the
  password-matching + strength-validation logic.

## Token / Session Handling

- `SESSION_COOKIE_HTTPONLY = True`, `SESSION_COOKIE_SAMESITE = 'Lax'`.
- `CSRF_COOKIE_HTTPONLY = True`, `CSRF_COOKIE_SAMESITE = 'Lax'` — the CSRF
  token is read from the server-rendered `{{ csrf_token }}` template
  variable for the `mark_watched` AJAX call, **never** from
  `document.cookie`. This was deliberately hardened: an earlier version of
  this project had `CSRF_COOKIE_HTTPONLY = False` on the (incorrect) belief
  that JS needed to read the cookie; confirmed no template or static JS
  file reads `document.cookie` anywhere, so it was switched back to
  Django's secure default.
- In production (`DEBUG=False`): `SESSION_COOKIE_SECURE = True`,
  `CSRF_COOKIE_SECURE = True`, `SECURE_SSL_REDIRECT` (default `True`,
  overridable), `SECURE_HSTS_SECONDS` (default 3600, overridable — intended
  to be raised once TLS is confirmed stable), `SECURE_PROXY_SSL_HEADER`
  set to trust `X-Forwarded-Proto` (required when TLS terminates at a
  proxy, e.g. Railway).
- `pending_google` session data (holds a verified-but-not-yet-actioned
  Google identity between OAuth callback and profile completion/linking) is
  never treated as authentication by itself — it only carries claims
  already cryptographically verified, and every consumer re-checks
  staleness (10-minute max age) via `_pending_google_data()`.
- The refresh/access token from Google is never requested or stored
  (`access_type: 'online'`, scopes limited to `openid email profile`) —
  nothing in this app calls another Google API on the user's behalf after
  sign-in.

## Input Validation

- All forms are Django `ModelForm`/`Form` — server-side validation via
  field types, `RegexValidator` (hex colors, YouTube video IDs),
  `MinValueValidator`/`MaxValueValidator` (quiz pass percentage), and
  custom `clean()` methods (`Comment.clean()` enforces one-level-deep
  threading and same-lesson parenting).
- `youtube_video_id` is regex-restricted (`^[A-Za-z0-9_-]{6,20}$`) because
  it's interpolated directly into an embed/thumbnail URL.
- `SlugFromNameMixin` (admin_panel forms) generates a slug from the source
  field during `clean()`, specifically so a slug collision surfaces as a
  normal form validation error (via `ModelForm._post_clean()`'s uniqueness
  check) rather than a raw `IntegrityError` if generated later in the view.

## CSRF / CORS

- `CsrfViewMiddleware` is enabled project-wide (Django default) — every
  POST form includes `{% csrf_token %}`; the AJAX endpoint sends it via the
  `X-CSRFToken` header.
- `CSRF_TRUSTED_ORIGINS` is env-configured (empty by default) for
  production domains allowed to POST.
- **No CORS configuration at all** (no `django-cors-headers`, no CORS
  middleware). There is no cross-origin API surface — every request this
  app serves is same-origin browser navigation/AJAX. If a cross-origin
  client is ever added, CORS will need to be introduced explicitly.

## File Upload Security

- `Resource.file`: `FileExtensionValidator` against an explicit allow-list
  (`ALLOWED_RESOURCE_EXTENSIONS` in `curriculum/models.py`) —
  `pdf, doc(x), ppt(x), xls(x), csv, txt, rtf`, image formats, `zip`.
  **Deliberately excludes** `html`, `htm`, `svg`, `xhtml`, `js` — anything a
  browser would execute when opened from `/media/`, since uploads are
  served from the app's own origin (same-origin execution risk if an
  attacker could upload and link to an HTML/SVG/JS file).
- `validate_resource_size` caps uploads at 25 MB per file so one staff
  account can't fill the disk.
- `Class.thumbnail`: separate `FileExtensionValidator` restricted to
  `png, jpg, jpeg, webp` only.
- Project-wide hard ceilings independent of the per-field validators:
  `FILE_UPLOAD_MAX_MEMORY_SIZE = 5MB`, `DATA_UPLOAD_MAX_MEMORY_SIZE = 30MB`,
  `DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000` — an oversized request is rejected
  before it's buffered to disk at all.
- Uploads are only reachable through `admin_panel`/Django Admin, i.e.
  staff-only — no unauthenticated upload endpoint exists.
- **Not implemented:** no virus/malware scanning of uploaded files; no
  content-sniffing beyond extension + `SECURE_CONTENT_TYPE_NOSNIFF`
  (browser-side MIME sniffing prevention, on by default).

## SQL Injection Protection

- 100% Django ORM — no raw SQL (`.raw()`, `cursor.execute()`) anywhere in
  the codebase. Django's ORM parameterizes queries by construction, so this
  class of vulnerability is not present in current code. Any future raw SQL
  would need to be parameterized manually.

## XSS Protection

- Django's template auto-escaping is on by default and not disabled
  anywhere (no `|safe` filter or `mark_safe()` calls found in templates or
  views) — user-supplied content (comment bodies, names, titles) is
  HTML-escaped on render.
- `SECURE_CONTENT_TYPE_NOSNIFF = True` — prevents the browser from
  MIME-sniffing responses into an executable type.
- `X_FRAME_OPTIONS = 'DENY'` — blocks this site from being framed
  (clickjacking defense), enforced by
  `django.middleware.clickjacking.XFrameOptionsMiddleware`.

## Rate Limiting

**Implemented**, via `django-ratelimit`, backed by `CACHES['default']`
(`LocMemCache`):

| View | Key | Rate | Notes |
|---|---|---|---|
| `login_view` (POST) | `ip` (via `accounts.ratelimit.get_client_ip`) | `LOGIN_RATE_LIMIT` (default `20/m`) | `block=False`; checked manually via `request.limited`, returns `429` with a friendly message |
| `google_callback_view` (GET) | `ip` | `LOGIN_RATE_LIMIT` | same pattern |
| `google_complete_profile_view` (POST) | `ip` | `REGISTRATION_RATE_LIMIT` (default `30/h`) | account-creation endpoint — this is where signup abuse is actually bounded, since there's no separate password-signup form to protect |
| `google_link_confirm_view` (POST) | `ip` | `LOGIN_RATE_LIMIT` | |
| `lesson_detail` (POST only, comment posting) | `user` (not `ip`) | `10/m` | GET (normal page views) is untouched; `key='user'` because `@login_required` already guarantees identity, so one student on a shared/NAT'd IP (e.g. a school network) can't be rate-limited by classmates |

- **Client IP extraction** (`accounts/ratelimit.py`): reads
  `X-Real-IP` rather than raw `REMOTE_ADDR` (which behind Railway's proxy
  is the proxy's own IP, collapsing every visitor into one shared bucket)
  and rather than `X-Forwarded-For` (Railway's own guidance on whether that
  header is trustworthy is genuinely conflicting — see the module's
  docstring for the full reasoning). Falls back to `REMOTE_ADDR` when
  neither header is present (local dev, and Django's test client).
- **Rate values are sized for this app's actual audience**: a school
  platform where a classroom on shared WiFi is one real public IP behind
  many real students (normal NAT geometry, not an attack). See
  `settings.py`'s comment block above `LOGIN_RATE_LIMIT` for the full
  reasoning; both limits are overridable per-deployment via env vars
  without a code change.
- **Known limitation:** `LocMemCache` is per-process. Rate-limit counters
  are **not shared across multiple gunicorn/uWSGI workers** — running N
  workers effectively multiplies every configured rate by N. Point `CACHES`
  at Redis or Memcached before deploying with more than one worker.

**Not implemented:**
- No rate limiting on the plain `lesson_detail` GET, `search_view`, or any
  `admin_panel` route (all staff-only, so lower-priority).
- No global/IP-wide request throttling — limits are per-view only.

## Secrets / Environment Variables

Managed via `python-decouple` (`config(...)`), sourced from `.env` locally
(gitignored) or the platform's environment/secrets panel in production.
Names only, no values, are referenced below and throughout this repo:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django's signing key (sessions, CSRF). **App refuses to boot** if `DEBUG=False` and this is still the `django-insecure-...` placeholder (hard `ImproperlyConfigured` at import time — see `settings.py`). |
| `DEBUG` | dev/prod switch |
| `ALLOWED_HOSTS` | comma-separated |
| `DATABASE_URL` | selects PostgreSQL when set; unset = SQLite |
| `DATABASE_SSL_REQUIRE` | TLS for the DB connection |
| `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` | all three required together for `GOOGLE_OAUTH_CONFIGURED` to be `True`; feature degrades gracefully (no signup button, informative redirect) when unset rather than breaking |
| `LOGIN_RATE_LIMIT`, `REGISTRATION_RATE_LIMIT` | overridable rate-limit strings |
| `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `CSRF_TRUSTED_ORIGINS` | production HTTPS/security headers |
| `DJANGO_LOG_LEVEL` | log verbosity |

`GOOGLE_OAUTH_CLIENT_SECRET` is used **only** inside
`accounts/google_oauth.py`'s server-side token exchange — it never reaches
a template, static JS file, or API response.

## Security-Sensitive Endpoints

- `/accounts/google/callback/` — validates OAuth `state`, exchanges/verifies
  the ID token server-side.
- `/account/delete/` — requires current password re-entry.
- `/panel/users/<pk>/toggle-staff/`, `/panel/users/<pk>/toggle-active/` —
  superuser-gated privilege escalation surface.
- `/admin/` — Django Admin, full model access for staff.

## Production Security Requirements (already enforced in code, not just documented)

- Real, unique `SECRET_KEY` — enforced by the `ImproperlyConfigured` guard.
- `DEBUG=False`.
- TLS terminated in front of the app with `X-Forwarded-Proto` set (if
  behind a proxy) — required for `SECURE_PROXY_SSL_HEADER` to work
  correctly; misconfiguring this can cause a redirect loop.
- `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` set to the real domain(s).
- If deploying more than one app worker/process: point `CACHES` at a shared
  backend (Redis/Memcached) before relying on rate limiting.

## Logging (security-relevant)

- `django.security` logger captures `SecurityMiddleware`/
  `CsrfViewMiddleware` events (disallowed hosts, CSRF failures, suspicious
  operations) automatically, routed to `logs/security.log` in production
  (kept longer than other logs — 10 rotated backups vs. 5 — as the audit
  trail).
- Application code explicitly logs: rate-limit hits (login, OAuth callback,
  profile completion, link-confirm, comment posting), OAuth `state`
  mismatches, non-superuser attempts at privilege-escalating actions,
  ambiguous-email OAuth matches (2+ existing users sharing an email).
- See [DEPLOYMENT.md](DEPLOYMENT.md) for where these logs actually persist
  in production (console is the durable record on an ephemeral filesystem
  host like Railway; local rotating files are a same-box convenience only).

## Known Security Gaps (recommended future improvements)

- No MFA.
- No password-reset-by-email flow.
- No CAPTCHA/bot-detection on login or the Google OAuth entry point beyond
  rate limiting.
- Rate limiting is not effective across multiple worker processes without
  a shared cache backend (documented above, not yet configured for that
  scenario).
- No automated dependency vulnerability scanning configured in this repo
  (no `pip-audit`/`safety`/Dependabot config present).
- No Content-Security-Policy header configured (Django has no CSP
  middleware enabled; would need `django-csp` or equivalent).
- No per-object permission checks on comments (no edit; delete is
  staff-only, not owner-only, by design — not a gap so much as a product
  choice worth confirming if requirements change).
