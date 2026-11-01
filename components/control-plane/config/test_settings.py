"""Isolated Django settings used only by pytest."""

import os
import tempfile
from .settings import *  # noqa: F403

SECRET_KEY = "keeplane-isolated-tests-signing-secret-never-used-by-the-application"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "OPTIONS": {"timeout": 20, "transaction_mode": "IMMEDIATE"},
        "TEST": {
            "NAME": os.path.join(
                tempfile.gettempdir(), f"keeplane-tests-{os.getpid()}.sqlite3"
            )
        },
    }
}
# Same stored algorithm as the application, at a test round count; see
# tests/support/password_hashing.py. The preview import hasher stays second.
PASSWORD_HASHERS = [
    "tests.support.password_hashing.LowRoundPBKDF2PasswordHasher",
    *PASSWORD_HASHERS[1:],  # noqa: F405
]
