"""Verify local availability of a server-managed shared provider key."""

import hashlib
import os
import stat
from pathlib import Path

from common.storage import storage_service
from integrations.gateway.keys import is_managed

from .fingerprints import fingerprint
from .models import ModelApproval
from .policy import ModelPolicyUnavailable, registry_rows


def managed_key_digest(directory, path):
    """Read a bounded valid managed key; return only its content digest."""
    if (
        not directory
        or not Path(directory).is_absolute()
        or not is_managed(directory, path)
    ):
        return False
    try:
        root = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            descriptor = os.open(
                Path(path).name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=root,
            )
            with os.fdopen(descriptor, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    return False
                # Existing storage accepts up to 512 UTF-8 characters.
                raw = source.read(2049)
                if len(raw) > 2048:
                    return False
                value = raw.decode("utf-8")
                # Preserve storage's character limit, including padding. Native
                # injection trims it; a blank secret or invalid HTTP field cannot work.
                valid = (
                    12 <= len(value) <= 512
                    and bool(value.strip())
                    and all(byte == 9 or (byte >= 32 and byte != 127) for byte in raw)
                )
                return hashlib.sha256(raw).hexdigest() if valid else None
        finally:
            os.close(root)
    except (OSError, UnicodeDecodeError, ValueError):
        return False


def managed_key_available(directory, path):
    return bool(managed_key_digest(directory, path))


@storage_service
class DjangoSharedKeyAvailability:
    def __init__(self, gateway, directory):
        self.gateway, self.directory = gateway, directory

    def require_available(self, model_id):
        approval = ModelApproval.objects.filter(pk=model_id).first()
        if approval is None:
            raise ModelPolicyUnavailable("Model setup is unavailable")
        if approval.key_choice == "none":
            return
        if approval.key_choice != "shared":
            raise ModelPolicyUnavailable("Provider key choice is unavailable")
        status, body = self.gateway.resources()
        if status != 200:
            raise ModelPolicyUnavailable("Provider key definition is unavailable")
        resources = registry_rows(body, "resources")
        if fingerprint(model_id, resources) != approval.gateway_fingerprint:
            raise ModelPolicyUnavailable("Provider key definition changed")
        resource = next(
            row.get("value", {}) for row in resources if row["id"] == model_id
        )
        try:
            path = resource.get("auth", {}).get("key", {}).get("value", {}).get("file")
        except (AttributeError, TypeError):
            path = None
        if not managed_key_available(self.directory, path):
            raise ModelPolicyUnavailable("Shared provider key is unavailable")
