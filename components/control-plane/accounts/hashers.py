"""Read existing preview passwords once; Django upgrades them on successful login."""

import hashlib
import hmac
from django.contrib.auth.hashers import BasePasswordHasher, mask_hash


class PreviewScryptHasher(BasePasswordHasher):
    algorithm = "keeplane_preview_scrypt"

    def verify(self, password, encoded):
        _, cost, parallelism, salt, expected = encoded.split("$", 4)
        if cost != "16384" or parallelism != "5":
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=5
        ).hex()
        return hmac.compare_digest(actual, expected)

    def safe_summary(self, encoded):
        return {
            "algorithm": self.algorithm,
            "hash": mask_hash(encoded.rsplit("$", 1)[-1]),
        }
