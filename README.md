# EduLearn — Django E-Learning Platform

A full-stack e-learning web application built with Django and Bootstrap 5.
Focused on Mathematics for Classes 6–12, scalable to any subject.

---

## Tech Stack

- **Backend:** Python 3.10+, Django 4.2
- **Frontend:** Django Templates, Bootstrap 5, Bootstrap Icons
- **Database:** SQLite (built-in, zero config)
- **Video Hosting:** YouTube Embed (iframe)

---

## Features

- 🔐 User authentication (register, login, logout)
- 📚 Curriculum: Class Level → Subject → Chapter → Lesson
- 🎬 YouTube video embed per lesson
- ✅ "Mark as Watched" with AJAX (no page reload)
- 📊 Progress tracking per subject on dashboard
- 📝 MCQ chapter quizzes with scoring and explanations
- 💬 Threaded comments/doubts per lesson
- 📄 PDF resource attachments per lesson
- 🛠️ Full Django Admin panel for content management

---

## Quick Start

### 1. Clone / Unzip the project

```bash
cd elearn_project
```

### 2. Create and activate virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

The `.env` file is already included with default settings for development.
To customize, edit `.env`:

```env
SECRET_KEY=your-very-secret-key-here
DEBUG=True
```

> ⚠️ For production, set `DEBUG=False` and use a strong, unique `SECRET_KEY`.

By default the app uses the zero-config SQLite file below — nothing else to do.
Set `DATABASE_URL` in `.env` to switch to PostgreSQL instead; see
[Migrating to PostgreSQL](#migrating-to-postgresql).

### 5. Run migrations

```bash
python manage.py migrate
```

### 6. Create a superuser (for Admin panel)

```bash
python manage.py createsuperuser
```

Follow the prompts to set username, email, and password.

### 7. Run the development server

```bash
python manage.py runserver
```

Visit: **http://127.0.0.1:8000**
Admin: **http://127.0.0.1:8000/admin**

---

## Adding Content via Admin Panel

1. Go to `/admin` and log in with your superuser account.
2. **Add a Subject** first (e.g., "Mathematics", slug: `mathematics`, icon: `bi-calculator`)
3. **Add a ClassLevel** linked to the subject (e.g., level 8, subject: Mathematics)
4. **Add a Chapter** linked to a ClassLevel (set title, slug, order)
5. **Add Lessons** inside a Chapter — paste just the YouTube **Video ID** (the part after `?v=` in the URL)
6. Optionally add **Resources** (PDF files) per lesson
7. Optionally add a **Quiz** per chapter with Questions and Choices

---

## Project Structure

```
elearn_project/
├── manage.py
├── requirements.txt
├── .env                        # Environment variables
├── .gitignore
├── db.sqlite3                  # Auto-created on first migrate
│
├── elearn_project/             # Django project config
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
│
├── core/                       # Main application
│   ├── models.py               # All database models
│   ├── views.py                # All views
│   ├── urls.py                 # URL patterns
│   ├── forms.py                # RegisterForm, CommentForm
│   └── admin.py                # Admin panel configuration
│
├── templates/
│   ├── base.html               # Master layout
│   └── core/
│       ├── landing.html        # Public homepage
│       ├── login.html
│       ├── register.html
│       ├── dashboard.html      # Subject overview + progress
│       ├── class_list.html     # Class level selector
│       ├── chapter_list.html   # Chapter accordion with lessons
│       ├── lesson_detail.html  # Video player + comments + sidebar
│       ├── quiz.html           # MCQ quiz form
│       └── quiz_result.html    # Score + answer review
│
├── static/                     # Your custom CSS/JS/images
│   ├── css/
│   ├── js/
│   └── images/
│
└── media/                      # Uploaded files (PDFs etc.)
```

---

## URL Structure

| URL | View | Description |
|-----|------|-------------|
| `/` | `landing` | Public homepage |
| `/register/` | `register_view` | Registration form |
| `/login/` | `login_view` | Login form |
| `/logout/` | `logout_view` | Logout |
| `/dashboard/` | `dashboard` | Subject cards + progress |
| `/learn/<subject>/` | `class_list` | Class level selector |
| `/learn/<subject>/class-<N>/` | `chapter_list` | Chapters accordion |
| `/learn/<subject>/class-<N>/<chapter>/<lesson>/` | `lesson_detail` | Video player |
| `/lesson/<id>/mark-watched/` | `mark_watched` | AJAX toggle (POST) |
| `/quiz/<chapter>/` | `quiz_view` | MCQ quiz + result |

---

## Adding More Subjects (Scalability)

1. In Django Admin, create a new **Subject** (e.g., "Physics", slug: `physics`, icon: `bi-lightning`)
2. Add **ClassLevels** for Physics
3. Add **Chapters** and **Lessons** as usual

The entire URL hierarchy automatically supports it — no code changes needed.

---

## YouTube Video ID

To find a video's ID:
- YouTube URL: `https://www.youtube.com/watch?v=dQw4w9WgXcQ`
- Video ID: `dQw4w9WgXcQ` ← paste only this into the admin

---

## Migrating to PostgreSQL

The project defaults to SQLite (zero config, one file, fine for development
and small deployments) but is ready for PostgreSQL for anything with real
concurrent traffic. Switching is a config change, not a code change — every
model and query in this project is plain Django ORM, no SQLite-specific SQL
anywhere.

**1. Install PostgreSQL** (skip if you already have a server — local or
managed, e.g. RDS/Cloud SQL/Supabase all work identically here).

**2. Create a database and a role for the app:**

```sql
CREATE DATABASE edulearn;
CREATE USER edulearn_app WITH PASSWORD 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON DATABASE edulearn TO edulearn_app;
```

**3. Set `DATABASE_URL` in `.env`** (this is the only settings.py-relevant
step — its presence is what switches the app off SQLite):

```env
DATABASE_URL=postgres://edulearn_app:choose-a-strong-password@localhost:5432/edulearn
```

Format: `postgres://USER:PASSWORD@HOST:PORT/NAME`. For a provider that
requires TLS (most managed Postgres does), also set:

```env
DATABASE_SSL_REQUIRE=True
```

**4. Install the Postgres driver** (already in `requirements.txt`, just
make sure it's installed in this environment):

```bash
pip install -r requirements.txt
```

**5. Run migrations against the new database:**

```bash
python manage.py migrate
```

This creates every table fresh — Subject through QuizAttempt, plus Django's
own auth/session/admin tables. Nothing here is SQLite-specific, so this is
the same `migrate` command either way.

**6. Moving existing data from SQLite (optional).** If you have real content
in `db.sqlite3` already, Django's `dumpdata`/`loaddata` round-trip carries it
over — run the dump *before* switching `DATABASE_URL`, and the load *after*:

```bash
# While still pointed at SQLite (no DATABASE_URL set):
python manage.py dumpdata --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.Permission -o data.json

# Set DATABASE_URL, run `migrate` (step 5), then:
python manage.py loaddata data.json
```

**7. Create a superuser on the new database** (existing SQLite users don't
carry over automatically unless included in the `dumpdata`/`loaddata` step
above):

```bash
python manage.py createsuperuser
```

**8. Run the app as usual** — `python manage.py runserver` (dev) or your
production WSGI server. Everything else (`media/`, `static/`, templates,
views) is unaffected by the database backend.

SQLite stays fully supported for local development either way — just don't
set `DATABASE_URL` and nothing changes from how the project has always run.

---

## Logging in production

Outside `DEBUG`, the app writes to `logs/edulearn.log`, `logs/errors.log`,
and `logs/security.log` (rotating, capped size) in addition to the console.
On Railway and most container platforms, that directory is writable but
**ephemeral** — anything not on a mounted Volume is wiped on every redeploy,
the same as `media/` uploads (see the PostgreSQL section above for the
general pattern). If the directory can't be created at all — a genuinely
read-only filesystem, a permissions problem — the app falls back to
console-only logging automatically rather than failing to start.

In practice this means:
- **Console output is the durable record on Railway** — it's what shows up
  in Railway's own Logs tab, and it survives redeploys because Railway
  captures it independently of the app's filesystem.
- The local files are a same-box, between-restarts convenience layered on
  top of that — useful for `tail`-ing recent activity in a shell on the
  box, not a substitute for the platform's own log view.
- If you want the rotating files to actually persist across deploys, mount
  a Railway Volume at `logs/`.

---

## License

MIT — free to use for educational purposes.
