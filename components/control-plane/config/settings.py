"""Django configuration for the local preview and shared PostgreSQL deployment."""

import os
from pathlib import Path
from urllib.parse import urlsplit

BASE_DIR = Path(__file__).resolve().parent.parent
PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN", "http://127.0.0.1:3000")
PUBLIC_ORIGIN_ALIASES = os.environ.get("PUBLIC_ORIGIN_ALIASES", "")
CSRF_TRUSTED_ORIGINS = [
    value.strip()
    for value in (PUBLIC_ORIGIN + "," + PUBLIC_ORIGIN_ALIASES).split(",")
    if value.strip()
]
ALLOWED_HOSTS = list(
    {
        "127.0.0.1",
        "localhost",
        *[
            urlsplit(origin).hostname
            for origin in CSRF_TRUSTED_ORIGINS
            if urlsplit(origin).hostname
        ],
    }
)
DEBUG = False
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "rest_framework",
    "common",
    "accounts",
    "model_registry",
    "data_classes",
    "audit",
]
MIDDLEWARE = [
    "common.middleware.StorageFailureMiddleware",
    "common.middleware.RequestLimitMiddleware",
    "common.middleware.PublicSchemeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "common.middleware.BrowserCsrfMiddleware",
]
AUTH_USER_MODEL = "accounts.User"
SESSION_ENGINE = "django.contrib.sessions.backends.db"
USE_TZ = True
TIME_ZONE = "UTC"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SECURE = PUBLIC_ORIGIN.startswith("https://")
CSRF_FAILURE_VIEW = "common.middleware.csrf_failure"
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "accounts.hashers.PreviewScryptHasher",
]

secret_file = os.environ.get("DJANGO_SECRET_KEY_FILE")
if secret_file:
    SECRET_KEY = Path(secret_file).read_text().strip()
else:
    # The launcher persists this file before any serving process starts.
    secret_path = Path(
        os.environ.get("KEEPLANE_SECRET_KEY_FILE", "/state/django-secret-key")
    )
    SECRET_KEY = secret_path.read_text().strip() if secret_path.is_file() else ""
if SECRET_KEY and len(SECRET_KEY) < 48:
    raise RuntimeError("The shared signing secret must be at least 48 characters")

if os.environ.get("KEEPLANE_DATABASE_HOST"):
    if not SECRET_KEY:
        raise RuntimeError("Configure a persistent Django signing secret")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "HOST": os.environ["KEEPLANE_DATABASE_HOST"],
            "PORT": os.environ.get("KEEPLANE_DATABASE_PORT", "5432"),
            "NAME": os.environ["KEEPLANE_DATABASE_NAME"],
            "USER": os.environ["KEEPLANE_DATABASE_USER"],
            "PASSWORD": Path(os.environ["KEEPLANE_DATABASE_PASSWORD_FILE"])
            .read_text()
            .strip(),
            "CONN_MAX_AGE": 0,
            "OPTIONS": {
                "connect_timeout": 5,
                "sslmode": os.environ.get("KEEPLANE_DATABASE_SSLMODE", "verify-full"),
            },
        }
    }
    if os.environ.get("KEEPLANE_DATABASE_SSLROOTCERT_FILE"):
        DATABASES["default"]["OPTIONS"]["sslrootcert"] = os.environ[
            "KEEPLANE_DATABASE_SSLROOTCERT_FILE"
        ]
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("KEEPLANE_SQLITE_PATH", "/state/keeplane.sqlite3"),
            # Reserve writes before reading state, including concurrent login budgets.
            "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
        }
    }

ADMIN_UI_DIR = Path(os.environ.get("KEEPLANE_UI_DIR", "/ui"))
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
