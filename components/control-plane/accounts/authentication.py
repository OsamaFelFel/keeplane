"""Explicit bearer access using current Django database sessions."""

import re
from urllib.parse import urlsplit

from django.conf import settings
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import APIException, AuthenticationFailed

from common.api import IDENTITY


class RuntimeAuthenticationUnavailable(APIException):
    status_code = 503
    default_detail = "Runtime access requires HTTPS, except on a loopback installation"


class RuntimeSessionAuthentication(BaseAuthentication):
    def authenticate(self, request):
        origin = urlsplit(settings.PUBLIC_ORIGIN)
        if not (
            origin.scheme == "https"
            or (
                origin.scheme == "http"
                and origin.hostname in {"localhost", "127.0.0.1", "::1"}
            )
        ):
            raise RuntimeAuthenticationUnavailable()
        parts = get_authorization_header(request).split()
        if (
            len(parts) != 2
            or parts[0].lower() != b"bearer"
            or not re.fullmatch(rb"[A-Za-z0-9_-]{1,200}", parts[1])
        ):
            raise AuthenticationFailed("Sign in to Keeplane")
        token = parts[1].decode("ascii")
        user = IDENTITY.authenticated_user(token)
        if user is None:
            raise AuthenticationFailed("Sign in to Keeplane")
        return user, token

    def authenticate_header(self, request):
        return "Bearer"


def runtime_bearer_only(view):
    """Mark explicit header-authenticated views for the browser CSRF boundary."""
    view.runtime_bearer_only = True
    return view
