from pathlib import Path

import dj_database_url
from decouple import Csv, config
from django.core.exceptions import ImproperlyConfigured

from .logging_config import ensure_log_dir

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-fallback-key-change-in-production')
DEBUG = config('DEBUG', default=True, cast=bool)

# Env-driven so deploying to a real domain is a config change, not a code change.
# Add your domain to ALLOWED_HOSTS in .env, comma separated.
ALLOWED_HOSTS = config(
    'ALLOWED_HOSTS',
    default='localhost,127.0.0.1,0.0.0.0,testserver',
    cast=Csv(),
)

# Refuse to boot in production on the placeholder key — otherwise session and
# CSRF signing are effectively public knowledge.
if not DEBUG and SECRET_KEY.startswith('django-insecure'):
    raise ImproperlyConfigured(
        'SECRET_KEY is still the development placeholder. Generate a real one '
        '(python -c "from django.core.management.utils import '
        'get_random_secret_key; print(get_random_secret_key())") and set it in '
        '.env before running with DEBUG=False.'
    )

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
    'accounts',
    'curriculum',
    'progress',
    'quizzes',
    'discussions',
    'admin_panel',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # Serves STATIC_ROOT directly from the app process — no nginx/CDN in
    # front on a platform like Railway, so without this, DEBUG=False means
    # no CSS/JS/icons at all (Django's own dev-only static() helper is
    # already gated off in urls.py). Must sit right after SecurityMiddleware
    # per whitenoise's own docs, before anything that might redirect.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'elearn_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'elearn_project.wsgi.application'

# ─── Database ──────────────────────────────────────────────────────────────────
# DATABASE_URL selects PostgreSQL for production — see README.md "Migrating
# to PostgreSQL" for the full setup. Left unset, this falls back to the
# zero-config SQLite file the project has always used, so local development
# needs no extra setup and nothing breaks for anyone who doesn't touch it.
#   DATABASE_URL=postgres://user:password@localhost:5432/edulearn
DATABASE_URL = config('DATABASE_URL', default='')

if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,  # persistent connections; avoid a new TCP+auth handshake every request
            conn_health_checks=True,
            ssl_require=config('DATABASE_SSL_REQUIRE', default=False, cast=bool),
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Compressed + cache-busting (hashed filenames) static storage in production;
# plain storage in dev, since the manifest backend requires collectstatic to
# have already run and fails hard on a missing file — friction dev doesn't
# need.
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': (
            'whitenoise.storage.CompressedManifestStaticFilesStorage'
            if not DEBUG else
            'django.contrib.staticfiles.storage.StaticFilesStorage'
        ),
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ─── Cache ─────────────────────────────────────────────────────────────────────
# Backs django-ratelimit's hit counters (see accounts/views.py: login_view,
# google_complete_profile_view; curriculum/views.py: lesson_detail). LocMemCache is fine for one process, but it's
# per-process memory — run more than one gunicorn/uWSGI worker and each worker
# enforces its own limit independently instead of a shared one, so the real
# limit becomes (configured rate) x (worker count). Point this at Redis or
# Memcached before deploying with multiple workers.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

# django-ratelimit's key='ip' would otherwise read REMOTE_ADDR, which behind
# any reverse proxy (Railway included) is the proxy's own IP — collapsing
# every visitor into one shared bucket. See accounts/ratelimit.py's docstring
# for the full reasoning and the (genuinely conflicting) platform guidance
# behind this specific choice of header.
RATELIMIT_IP_META_KEY = 'accounts.ratelimit.get_client_ip'

# Sized for this app's actual audience, not a generic default: this is a
# school platform, and a classroom on shared WiFi is one real public IP
# with many real students behind it — that's normal NAT geometry, not a
# bug, and correct per-visitor IP extraction (above) can't split it apart.
# 5/hour for registration was tight enough that a teacher enrolling a
# class of 25-30 in one sitting would legitimately hit it; 5/minute for
# login was tight enough that "everyone log in now" at the start of class
# could too. Both are raised to comfortably clear a full classroom while
# still bounding pure automation (a script trying hundreds of signups or
# password guesses in the same window). Overridable per-deployment without
# a code change if a given school's numbers warrant it.
LOGIN_RATE_LIMIT = config('LOGIN_RATE_LIMIT', default='20/m')
REGISTRATION_RATE_LIMIT = config('REGISTRATION_RATE_LIMIT', default='30/h')

# ─── Google OAuth ──────────────────────────────────────────────────────────────
# See accounts/google_oauth.py for the flow itself and README.md for the exact
# Google Cloud Console setup steps. All three blank by default so a fresh
# checkout without Google credentials configured just doesn't show the
# "Continue with Google" button — the rest of the app is unaffected either
# way (see GOOGLE_OAUTH_CONFIGURED below).
GOOGLE_OAUTH_CLIENT_ID = config('GOOGLE_OAUTH_CLIENT_ID', default='')
GOOGLE_OAUTH_CLIENT_SECRET = config('GOOGLE_OAUTH_CLIENT_SECRET', default='')
# Deliberately a fixed, explicitly configured value rather than built from
# request.build_absolute_uri() at request time: Google itself validates this
# against what's registered on the OAuth client, but deriving it from the
# incoming request would mean trusting the Host header for something
# security-relevant, which is bad practice even when something else also
# catches the mistake. Must exactly match a redirect URI registered in
# Google Cloud Console — e.g. http://127.0.0.1:8000/accounts/google/callback/
# for local dev, https://<your-domain>/accounts/google/callback/ in
# production.
GOOGLE_OAUTH_REDIRECT_URI = config('GOOGLE_OAUTH_REDIRECT_URI', default='')

GOOGLE_OAUTH_CONFIGURED = bool(
    GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET and GOOGLE_OAUTH_REDIRECT_URI
)

# ─── Upload limits ─────────────────────────────────────────────────────────────
# Hard ceilings independent of the per-field validators in curriculum.models, so an
# oversized request is rejected before it is buffered to disk.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024      # 5 MB kept in memory
DATA_UPLOAD_MAX_MEMORY_SIZE = 30 * 1024 * 1024     # 30 MB total request body
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

# ─── Security ──────────────────────────────────────────────────────────────────
# On by default in Django, restated here so they are visible and auditable.
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_HTTPONLY = True
# Django's secure default. Previously disabled with a comment claiming the
# lesson page's AJAX call needed to read the cookie via JavaScript — it
# doesn't: templates/curriculum/lesson_detail.html gets its token from the
# server-rendered {{ csrf_token }} template variable, never from
# document.cookie (confirmed: no template or static JS in this project reads
# `document.cookie` or a `csrftoken` cookie anywhere). Leaving it False bought
# nothing and gave a future XSS one more thing it could steal.
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'

if not DEBUG:
    # HTTPS-only cookies and redirects. Requires TLS terminated in front of the
    # app; if that is a proxy, it must set X-Forwarded-Proto.
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Start HSTS short (e.g. 3600) and raise it once you're sure about TLS —
    # browsers honour the max-age even after you stop sending the header.
    SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=3600, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = config(
        'SECURE_HSTS_INCLUDE_SUBDOMAINS', default=False, cast=bool
    )
    SECURE_HSTS_PRELOAD = False

    # Domains allowed to POST to us, e.g. https://edulearn.example.com
    CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())

# ─── Logging ───────────────────────────────────────────────────────────────────
# Console always; rotating log files only outside DEBUG, so a local dev
# checkout never accumulates log files nobody asked for. `accounts`,
# `curriculum`, `progress` and `admin_panel` are this project's own loggers
# (see the logger.warning calls in their respective views.py) — everything
# else here is Django's own logging plumbed to somewhere durable instead of
# just stdout.
LOG_LEVEL = config('DJANGO_LOG_LEVEL', default='INFO')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'simple': {'format': '{levelname} {name}: {message}', 'style': '{'},
        'verbose': {
            'format': '{asctime} {levelname} {name} {module}:{lineno} — {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'DEBUG' if DEBUG else LOG_LEVEL,
            'formatter': 'simple' if DEBUG else 'verbose',
        },
    },
    'root': {'handlers': ['console'], 'level': LOG_LEVEL},
    'loggers': {
        'django': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        # Django logs every unhandled 500 here regardless of this config;
        # routing it to its own handler in prod is what makes it findable.
        'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
        # Populated automatically by SecurityMiddleware/CsrfViewMiddleware —
        # disallowed hosts, CSRF failures, suspicious operations — with zero
        # application code needed for that part.
        'django.security': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
        'core': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'accounts': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'curriculum': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'progress': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
        'admin_panel': {'handlers': ['console'], 'level': LOG_LEVEL, 'propagate': False},
    },
}

if not DEBUG and ensure_log_dir(BASE_DIR / 'logs'):
    # Guarded by ensure_log_dir() rather than creating the directory inline:
    # most hosts (Railway included) have a writable runtime filesystem, but
    # files written outside an explicitly mounted volume don't survive a
    # redeploy there either way — console output is what Railway's own
    # dashboard actually captures durably. These files are a same-box,
    # between-restarts convenience on top of that, not the durable record;
    # if the directory can't be created at all (a genuinely read-only
    # container root, a permissions problem, a full disk), degrade to
    # console-only instead of crashing the whole app at import time.
    LOG_DIR = BASE_DIR / 'logs'

    LOGGING['handlers'].update({
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'edulearn.log',
            'maxBytes': 5 * 1024 * 1024,  # 5 MB
            'backupCount': 5,
            'level': LOG_LEVEL,
            'formatter': 'verbose',
            # Explicit, not host-default: RotatingFileHandler otherwise opens
            # files with the OS locale encoding, which mangles the em-dash in
            # the 'verbose' formatter (and anything else non-ASCII) on
            # Windows. Pin UTF-8 so log files are correct regardless of what
            # the host's default locale happens to be.
            'encoding': 'utf-8',
        },
        'error_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'errors.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 5,
            'level': 'ERROR',
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
        'security_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'security.log',
            'maxBytes': 5 * 1024 * 1024,
            'backupCount': 10,  # kept longer than the others — this is the audit trail
            'level': 'WARNING',
            'formatter': 'verbose',
            'encoding': 'utf-8',
        },
    })
    LOGGING['root']['handlers'] = ['console', 'file']
    for logger_name in ('django', 'core', 'accounts', 'curriculum', 'progress', 'admin_panel'):
        LOGGING['loggers'][logger_name]['handlers'] = ['console', 'file']
    LOGGING['loggers']['django.request']['handlers'] = ['console', 'error_file']
    LOGGING['loggers']['django.security']['handlers'] = ['console', 'security_file']

# Auth redirects
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'landing'
