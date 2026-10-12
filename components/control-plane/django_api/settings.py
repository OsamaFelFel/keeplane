"""Local account API settings; release persistence remains a separate gate."""

import os
import secrets

SECRET_KEY = secrets.token_urlsafe(48)
DEBUG = False
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]
ROOT_URLCONF = "django_api.urls"
INSTALLED_APPS = ["rest_framework"]
MIDDLEWARE = ["django_api.security.BrowserCsrfMiddleware"]
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
