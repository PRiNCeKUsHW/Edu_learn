# DECISIONS.md

Architectural decisions worth understanding before changing them, in
ADR-lite form. These are reconstructed from the reasoning already recorded
in code comments and docstrings throughout the repo — this file collects
them in one place rather than duplicating models/views detail found in
[ARCHITECTURE.md](ARCHITECTURE.md), [DATABASE.md](DATABASE.md), and
[SECURITY.md](SECURITY.md).

---

### The curriculum hierarchy is entirely admin-authored data, never hardcoded

**Decision:** `CourseKind → Class → Subject → Chapter → Lesson` carries no
built-in vocabulary. A fresh database has zero rows at every level; nothing
ships pre-defined.

**Why:** the same codebase needs to run a school, a coaching institute, a
bootcamp, a language academy, or a corporate training portal without a code
change — see README.md's "Building a Different Kind of Platform" table.

**Consequence:** don't special-case any level for a particular domain
("a class has grades", "a subject implies a syllabus code"). Tests
explicitly guard this (`curriculum/tests/test_hierarchy.py:NoHardcodedStructureTests`).

---

### No custom user model — `GoogleAccount` extends `User` via `OneToOneField`

**Decision:** `accounts.GoogleAccount` is a one-to-one extension of Django's
stock `django.contrib.auth.User`, not a swap of `AUTH_USER_MODEL`.

**Why:** `AUTH_USER_MODEL` can't safely be changed this late in an existing
project — every other model (`LessonProgress`, `Comment`, `QuizAttempt`)
and the entire admin panel's user management already depend on the stock
`User`. This is the standard, low-risk way to add OAuth identity onto an
existing auth system.

**Consequence:** any future per-user field (e.g. a bio, an avatar) should
follow the same pattern — a new one-to-one "profile" model — rather than
attempting a user-model swap.

---

### `admin_panel` has no models — it's a pure CRUD UI over other apps

**Decision:** `admin_panel` imports and operates on `curriculum`,
`quizzes`, and `discussions` models directly; it owns no schema.

**Consequence:** a new staff-manageable content type's model belongs in its
domain app, not `admin_panel`. `admin_panel` only gets the forms/views/URLs.

---

### Two separate staff surfaces: Django Admin and `/panel/`

**Decision:** both `/admin/` (Django's built-in admin, full unrestricted
model access, inlines) and `/panel/` (this project's own curated CRUD UI,
`staff_member_required`, workflow-shaped for the specific tasks staff do
day to day — e.g. "add a question, land straight on adding its choices")
exist side by side and are both actively used.

**Why:** Django Admin is unopinionated and fast to get for free; `/panel/`
encodes the actual authoring workflow (slug autofill, guided next-steps,
student reports, superuser-gated user management) that Django Admin alone
doesn't provide without heavy customization.

**Consequence:** don't try to consolidate them into one — they serve
different purposes. New guided/workflow-shaped staff features belong in
`/panel/`; raw data-fixing access belongs in `/admin/`.

---

### Comment posting lives inside `curriculum.views.lesson_detail`, not `discussions`

**Decision:** `discussions` owns the `Comment` model and `CommentForm`, but
the actual POST-handling logic for creating a comment is inline in
`curriculum.views.lesson_detail`.

**Why:** extracting it into its own `discussions` view would change the
form's POST target and add behavioral risk for no real gain — a comment
always redirects back to the same lesson page regardless of which view
handled the POST.

**Consequence:** don't "clean this up" into a separate endpoint without a
concrete reason; it was a deliberate choice, not an oversight.

---

### SQLite by default, PostgreSQL opt-in via `DATABASE_URL`

**Decision:** the app runs on SQLite with zero configuration; setting
`DATABASE_URL` switches to PostgreSQL with no code change.

**Why:** SQLite is fine for development and small deployments; every model
and query is plain Django ORM with no SQLite-specific SQL, so the switch is
purely a config decision, not an engineering one.

**Consequence:** never write raw SQL or backend-specific field options —
see [DATABASE.md](DATABASE.md). `dumpdata`/`loaddata` is the documented
path for moving existing SQLite content to Postgres (README.md).

---

### WhiteNoise serves static files — no nginx/CDN in front

**Decision:** `whitenoise.middleware.WhiteNoiseMiddleware` serves
`STATIC_ROOT` directly from the gunicorn process.

**Why:** matches a single-process Railway-style deploy with no reverse
proxy for static assets. Without it, `DEBUG=False` would mean no CSS/JS/
icons at all, since Django's own dev `static()` helper is explicitly
gated off outside `DEBUG`.

**Consequence:** `/media/` has no equivalent solution yet — see
[DEPLOYMENT.md](DEPLOYMENT.md)'s note that production media serving is an
open task, not a solved one.

---

### Server-side OAuth "authorization code" flow, not Google's client-side JS widget

**Decision:** `accounts/google_oauth.py` implements the plain
browser-redirect-to-Google-and-back flow, not Google's "Sign In With
Google" JS widget.

**Why:** `GOOGLE_OAUTH_CLIENT_SECRET` never reaches the browser, and every
verification step (state, signature, audience, expiry, issuer,
`email_verified`) happens server-side — nothing about the caller's own
claims is ever trusted client-side.

**Consequence:** don't introduce a client-side token-verification shortcut;
keep the secret and all verification server-side.

---

### `GOOGLE_OAUTH_REDIRECT_URI` is a fixed config value, never derived from the request

**Decision:** the redirect URI used in both the authorization request and
the token exchange comes from a settings value, not
`request.build_absolute_uri()`.

**Why:** deriving it from the incoming request means trusting the `Host`
header for something security-relevant — Google validates it against the
registered OAuth client regardless, but this avoids relying on that as the
only backstop.

**Consequence:** if multi-domain support is ever needed, add explicit
per-domain configuration rather than deriving the URI dynamically.

---

### `CSRF_COOKIE_HTTPONLY = True` — the AJAX endpoint reads the token from the template, not the cookie

**Decision:** the CSRF cookie is `HttpOnly`; `mark_watched`'s `fetch()` call
sends the token from `{{ csrf_token }}` rendered server-side into the page.

**Why:** an earlier version of this project set `CSRF_COOKIE_HTTPONLY =
False` on the belief that the AJAX call needed to read the cookie via
JavaScript. It doesn't — confirmed no template or static JS anywhere reads
`document.cookie` or a `csrftoken` cookie. Leaving it `False` bought
nothing functionally and gave a future XSS one more thing to steal.

**Consequence:** any new AJAX endpoint should follow the same pattern —
token from a server-rendered template variable, not from reading the
cookie in JS.

---

### `X-Real-IP` over `X-Forwarded-For` for rate-limit client identification

**Decision:** `accounts/ratelimit.py:get_client_ip` reads `X-Real-IP`,
falling back to `REMOTE_ADDR`, and deliberately does **not** use
`X-Forwarded-For`.

**Why:** raw `REMOTE_ADDR` behind Railway's proxy is the proxy's own IP,
collapsing every visitor into one shared rate-limit bucket. Railway's own
support guidance on whether `X-Forwarded-For` is safe to trust directly is
genuinely conflicting (client-supplied values may or may not be stripped at
the edge, depending on which Railway source you believe) — trusting it
uncritically would let an attacker spoof their own rate-limit bucket.
`X-Real-IP` is Railway's own recommended, unambiguous answer. The one known
caveat (traffic through Railway's CDN/custom-domain layer can reflect the
CDN edge's IP rather than the visitor's) degrades to the *original* problem
(several real users briefly sharing one bucket) rather than a security
bypass — the safer failure mode of the two options.

**Consequence:** don't switch this to `X-Forwarded-For` without re-solving
the spoofing concern; don't remove the `REMOTE_ADDR` fallback (it's what
keeps local dev and the test client working).

---

### Rate limits sized for classroom NAT geometry, not generic defaults

**Decision:** `LOGIN_RATE_LIMIT` defaults to `20/m`, `REGISTRATION_RATE_LIMIT`
to `30/h` — deliberately higher than a typical generic default.

**Why:** this is a school platform; a classroom on shared WiFi is one real
public IP with many real students behind it (normal NAT geometry, not an
attack). The original tighter values (5/hour registration, 5/minute login)
were tight enough that a teacher enrolling 25-30 students in one sitting,
or a whole class logging in at the start of a lesson, would legitimately
trip the limit.

**Consequence:** don't "tighten this back down for security" without
accounting for the classroom-NAT scenario; both values are overridable
per-deployment via env vars if a specific school's numbers warrant it.

---

### Quiz answers are persisted as `QuizAnswer` rows, not reconstructed from session/POST data

**Decision:** every quiz submission writes one `QuizAnswer` row per
question (`selected_choice`, `is_correct` computed and stored at submission
time), in addition to the `QuizAttempt` summary row.

**Why:** this is what lets "View analysis" (`quiz_analysis_view`) rebuild
the exact result/answer-review screen for a past attempt later, without
needing the original POST data or a session that may have expired.

**Consequence:** don't try to recompute `is_correct` at analysis time from
current `Choice.is_correct` values — it's intentionally a frozen snapshot
of what was true (and what was selected) at submission time; if a
`Choice.is_correct` flag is edited later by staff, past attempts should
still reflect what was graded then.

---

### Every quiz retake creates a new `QuizAttempt` — history is never overwritten

**Decision:** `QuizAttempt` has no upsert/overwrite behavior; each
submission is a new row.

**Why:** students and staff (via `student_report`) should be able to see
improvement across retakes, not just the latest score.

**Consequence:** any "quizzes passed" aggregate must dedupe explicitly
(`.values('quiz').distinct()`, as `progress.views.dashboard` does) rather
than assuming one row per quiz per student.
