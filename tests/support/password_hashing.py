"""Test-only password hashing: the application's algorithm at a test work factor.

Django's PBKDF2 default does a million SHA-256 rounds per password, by design.
In-process tests hash and check passwords for nearly every signed-in case, so
that cost dominated the backend run. This hasher keeps the same algorithm name
and stored format, so hashes written here are still checked by the application
hasher in separately started processes (and the other way round); only the
round count is lowered. The application settings are unchanged.
"""

from django.contrib.auth.hashers import PBKDF2PasswordHasher

TEST_ITERATIONS = 1_000


class LowRoundPBKDF2PasswordHasher(PBKDF2PasswordHasher):
    iterations = TEST_ITERATIONS
