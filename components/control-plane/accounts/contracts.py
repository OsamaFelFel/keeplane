"""Account validation, public representations and sign-in limits."""

import hashlib
import re

SESSION_SECONDS = 8 * 60 * 60


LOGIN_ATTEMPTS = 5


LOGIN_WINDOW_SECONDS = 60


USERNAME_PATTERN = re.compile(r"[A-Za-z0-9._-]{3,64}\Z")


class IdentityError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


class LoginThrottled(IdentityError):
    def __init__(self, retry_after):
        super().__init__(429, "Too many sign-in attempts. Wait a minute and try again.")
        self.retry_after = retry_after


def login_bucket(username):
    # Match SQLite's case-insensitive ASCII usernames without storing their text.
    return hashlib.sha256(username.lower().encode()).hexdigest()


def pagination(query):
    try:
        page = int(query.get("page", ["1"])[0])
        size = int(query.get("page_size", ["20"])[0])
    except ValueError:
        raise IdentityError(400, "Page and page size must be numbers")
    if page < 1 or page > 10000 or size < 1 or size > 50:
        raise IdentityError(400, "Page must be positive and page size at most 50")
    return page, size


def public_user(row):
    user = dict(row)
    user["managed"] = user["username"] == "first-admin"
    user["sign_in"] = "break-glass" if user["managed"] else "local"
    return user
