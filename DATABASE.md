# DATABASE.md

Current schema, described conceptually rather than by pasting the ORM
source. See the actual `models.py` in each app for full field definitions;
this file documents relationships, constraints, and the business rules the
database enforces.

## Technology

- **Local/default:** SQLite (`db.sqlite3` in the project root, zero config).
- **Production-capable:** PostgreSQL, selected automatically when the
  `DATABASE_URL` env var is set (parsed by `dj-database-url`, driver
  `psycopg[binary]`). Connection pooling: `conn_max_age=600`,
  `conn_health_checks=True`. TLS via `DATABASE_SSL_REQUIRE`.
- Every model uses plain Django ORM with no backend-specific SQL, so the
  same migrations apply cleanly to either backend. See README.md's
  "Migrating to PostgreSQL" section for the operational steps
  (`dumpdata`/`loaddata` to carry over existing SQLite data).
- `DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'` — all PKs are
  64-bit auto-incrementing integers.

## Entity-Relationship Overview

```mermaid
erDiagram
    User ||--o| GoogleAccount : "OAuth identity"
    User ||--o{ LessonProgress : "watches"
    User ||--o{ QuizAttempt : "attempts"
    User ||--o{ Comment : "posts"

    CourseKind ||--o{ Class : "optional grouping"
    Class ||--o{ Subject : "has"
    Subject ||--o{ Chapter : "has"
    Chapter ||--o{ Lesson : "has"
    Chapter ||--o| Quiz : "has one"
    Lesson ||--o{ Resource : "has"
    Lesson ||--o{ LessonProgress : "tracked by"
    Lesson ||--o{ Comment : "discussed in"

    Quiz ||--o{ Question : "has"
    Question ||--o{ Choice : "has"
    Quiz ||--o{ QuizAttempt : "attempted as"
    QuizAttempt ||--o{ QuizAnswer : "records"
    QuizAnswer }o--|| Question : "answers"
    QuizAnswer }o--o| Choice : "selected"

    Comment ||--o{ Comment : "one level of replies"
```

## Tables / Models

### `accounts.GoogleAccount`
Links a Django `User` to a verified Google identity for OAuth sign-in.
| Field | Notes |
|---|---|
| `user` | `OneToOneField(User, on_delete=CASCADE)` |
| `google_id` | `unique`, indexed — Google ID token's `sub` claim, the permanent identifier (not email, which can change) |
| `email` | Email at link time, for display/audit; live email is on `User.email` |
| `email_verified` | Always `True` in practice (only ever created after checking the claim); stored explicitly for audit |
| `linked_at` | `auto_now_add` |

No custom user model — see [DECISIONS.md](DECISIONS.md).

### `curriculum.CourseKind`
Optional category label for a `Class` (e.g. "School", "Bootcamp").
`name`, `slug` (unique, auto-filled from name), `description`, `icon`
(Bootstrap Icons class), `color` (hex, regex-validated `#RRGGBB`),
`is_active`, `order`.

### `curriculum.Class`
Top of the hierarchy; what a student picks on the dashboard.
`name`, `slug` (**globally unique**, auto-filled), `kind` (FK →
`CourseKind`, `SET_NULL`, optional — deleting a kind never cascades into
losing classes/lessons), `description`, `thumbnail` (image, extension
validated), `icon`, `is_active`, `order`, `created_at`.

### `curriculum.Subject`
A division of a `Class`. `klass` (FK → `Class`, `CASCADE`; named `klass`
because `class` is a Python keyword — templates read `subject.klass.name`),
`name`, `slug`, `description`, `icon_class`, `is_active`, `order`,
`created_at`.
**Constraint:** `unique_together = ('klass', 'slug')` — slug is scoped per
class, so two different classes can each have their own `maths`.

### `curriculum.Chapter`
`subject` (FK → `Subject`, `CASCADE`), `title`, `slug`, `order`,
`description`.
**Constraint:** `unique_together = ('subject', 'slug')` — slug unique only
within its subject. Lookups must always be scoped through the full
`Class → Subject` chain (see `curriculum.views._get_subject`), or a bare
slug lookup can raise `MultipleObjectsReturned` once two chapters in
different classes/subjects happen to share a slug.

### `curriculum.Lesson`
Single video lesson; stores only the YouTube Video ID.
`chapter` (FK → `Chapter`, `CASCADE`), `title`, `slug`, `order`,
`youtube_video_id` (regex-validated `^[A-Za-z0-9_-]{6,20}$` — interpolated
directly into embed/thumbnail URLs, so the charset is restricted),
`description`, `duration_minutes`, `created_at`.
**Constraint:** `unique_together = ('chapter', 'slug')`.
**Computed properties** (not DB fields): `youtube_embed_url`,
`youtube_thumbnail_url`.

### `curriculum.Resource`
A file attachment (PDF, doc, etc.) on a `Lesson`.
`lesson` (FK → `Lesson`, `CASCADE`), `title`, `file` (`FileField`,
`upload_to='resources/%Y/%m/'`), `uploaded_at`.
**Validation (enforced at the model/form layer, not the DB):**
`FileExtensionValidator` against an explicit allow-list (`pdf`, `doc(x)`,
`ppt(x)`, `xls(x)`, `csv`, `txt`, `rtf`, image formats, `zip` — deliberately
excludes `html`/`htm`/`svg`/`xhtml`/`js`, since uploads are served from the
site's own origin) plus a 25 MB size cap (`validate_resource_size`).
`Class.thumbnail` has a parallel image-only extension validator.

### `progress.LessonProgress`
Per-user watch state for a lesson.
`user` (FK → `User`, `CASCADE`), `lesson` (FK → `'curriculum.Lesson'`,
`CASCADE`, string reference to avoid a circular import), `watched`
(boolean), `watched_at` (nullable — set when `watched` flips `True`,
cleared when it flips back).
**Constraint:** `unique_together = ('user', 'lesson')` — one row per
user/lesson pair; `get_or_create` is the standard access pattern (see
`progress.views.mark_watched`, `curriculum.views.lesson_detail`).

### `quizzes.Quiz`
**One quiz per chapter.** `chapter` (`OneToOneField` → `'curriculum.Chapter'`,
`CASCADE`), `title`, `description`, `pass_percentage` (1–100, validated).

### `quizzes.Question`
`quiz` (FK → `Quiz`, `CASCADE`), `text`, `order`, `explanation` (shown after
answering).

### `quizzes.Choice`
`question` (FK → `Question`, `CASCADE`), `text`, `is_correct` (boolean).
No DB-level constraint forces "exactly one correct choice per question" —
that's enforced only by admin UI convention (`ChoiceInline` in Django Admin
sets `min_num = 2`, `extra = 4`).

### `quizzes.QuizAttempt`
One row per submission (history is kept, not overwritten, so retakes show
improvement over time).
`user` (FK, `CASCADE`), `quiz` (FK, `CASCADE`), `score`, `total`, `passed`
(boolean), `attempted_at` (`auto_now_add`). Ordered `-attempted_at` by
default. Computed property: `percentage`.

### `quizzes.QuizAnswer`
Which choice a student picked for one question of a stored `QuizAttempt` —
persisted so "View analysis" can rebuild the answer review without the
original POST data.
`attempt` (FK → `QuizAttempt`, `CASCADE`), `question` (FK → `Question`, no
reverse accessor — `related_name='+'`), `selected_choice` (FK → `Choice`,
`SET_NULL`, nullable — an unanswered question still gets a row with
`selected_choice=None`), `is_correct` (boolean, computed at submission time
and stored, not recalculated later).
**Constraint:** `unique_together = ('attempt', 'question')`.

### `discussions.Comment`
One-level-deep threaded comments/doubts on a lesson.
`lesson` (FK → `'curriculum.Lesson'`, `CASCADE`), `user` (FK → `User`,
`CASCADE`), `parent` (self-FK, nullable, `CASCADE`), `body`, `created_at`,
`updated_at` (`auto_now`).
**Business rule enforced in `Comment.clean()`, not a DB constraint:** a
reply must belong to the same lesson as its parent, and threads are exactly
one level deep (a reply's parent must itself have no parent). The template
only ever renders `parent → replies`, so a deeper nest would be invisible
even if it existed — `clean()` is what actually prevents it, and it's only
called on forms that call `full_clean()`/`ModelForm.is_valid()`
(`discussions.forms.CommentForm`), not on arbitrary `.save()` calls.

## Cascade Behavior Summary

Deleting a `User` cascades through `GoogleAccount`, `LessonProgress`,
`QuizAttempt`, and `Comment` — see `accounts.views.account_delete_view`'s
docstring, which relies on this explicitly (self-service account deletion
needs no extra signal handling). Deleting a `CourseKind` does **not** cascade
into `Class` (`SET_NULL`) — classes and their lessons survive. Everything
below `Class` (`Subject` → `Chapter` → `Lesson` → `Resource`/`Quiz`/
`LessonProgress`/`Comment`) cascades on delete, so deleting a `Class` deletes
its entire subtree.

## Migration Strategy

Standard Django migrations, one `migrations/` directory per app:

| App | Migrations |
|---|---|
| `accounts` | `0001_initial` |
| `curriculum` | `0001_initial`, `0002_alter_chapter_slug_alter_class_slug_and_more` |
| `progress` | `0001_initial` |
| `quizzes` | `0001_initial`, `0002_quizanswer` (added `QuizAnswer` for attempt-history replay) |
| `discussions` | `0001_initial` |
| `core` | none (no models) |

No data migrations or custom migration operations — everything is standard
schema migrations generated by `makemigrations`. See
[AGENTS.md](AGENTS.md#migration-rules) for the rule on hand-editing.

## Seed / Initial Data

**None.** There are no fixtures and no seed command — a fresh database has
zero `CourseKind`/`Class`/`Subject`/`Chapter`/`Lesson` rows by design (this
is the platform's core premise: the admin builds the entire hierarchy from
an empty database via `/panel/` or `/admin/`). The only way to populate
content is through those UIs, or via `dumpdata`/`loaddata` when migrating
existing data between environments (see README.md).
