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
