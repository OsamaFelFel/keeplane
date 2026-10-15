"""Local account API settings; release persistence remains a separate gate."""

import os
import secrets
from pathlib import Path

SECRET_KEY = secrets.token_urlsafe(48)
DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
ROOT_URLCONF = "django_api.urls"
INSTALLED_APPS = ["rest_framework"]
MIDDLEWARE = ["django_api.security.StorageFailureMiddleware", "django_api.security.BrowserCsrfMiddleware"]
PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN", "")
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in
                        (PUBLIC_ORIGIN + "," + os.environ.get("PUBLIC_ORIGIN_ALIASES", "")).split(",")
                        if origin.strip()]
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_COOKIE_SECURE = PUBLIC_ORIGIN.startswith("https://")
CSRF_FAILURE_VIEW = "django_api.security.csrf_failure"
# The loopback edge sets this from deployment configuration, never from a client header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_KEEPLANE_SCHEME", "https")
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
}

if os.environ.get("KEEPLANE_DATABASE_HOST"):
    # No random signing key or SQLite fallback in shared-database mode.
    SECRET_KEY = Path(os.environ["DJANGO_SECRET_KEY_FILE"]).read_text().strip()
    if len(SECRET_KEY) < 48:
        raise RuntimeError("The shared signing secret must be at least 48 characters")
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.environ["KEEPLANE_DATABASE_HOST"],
        "PORT": os.environ.get("KEEPLANE_DATABASE_PORT", "5432"),
        "NAME": os.environ["KEEPLANE_DATABASE_NAME"],
        "USER": os.environ["KEEPLANE_DATABASE_USER"],
        "PASSWORD": Path(os.environ["KEEPLANE_DATABASE_PASSWORD_FILE"]).read_text().strip(),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"connect_timeout": 5, "sslmode": os.environ.get("KEEPLANE_DATABASE_SSLMODE", "verify-full")},
    }}
    if os.environ.get("KEEPLANE_DATABASE_SSLROOTCERT_FILE"):
        DATABASES["default"]["OPTIONS"]["sslrootcert"] = os.environ["KEEPLANE_DATABASE_SSLROOTCERT_FILE"]
    INSTALLED_APPS += ["django.contrib.contenttypes", "django.contrib.auth",
                       "django.contrib.sessions", "django_api.accounts"]
    AUTH_USER_MODEL = "accounts.User"
    SESSION_ENGINE = "django.contrib.sessions.backends.db"
    USE_TZ = True
    TIME_ZONE = "UTC"
    DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
