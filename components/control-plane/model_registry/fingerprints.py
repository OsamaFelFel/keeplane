"""Bind model approval to a specific gateway definition."""

import hashlib
import json
from pathlib import Path


def fingerprint(model_id, resources, file_owned_config=None):
    """Bind approval to the gateway definition and its update revision."""
    entry = next((item for item in resources if item.get("id") == model_id), None)
    if entry is None:
        if model_id == "local-fixture" and file_owned_config:
            try:
                return (
                    "file-owned:"
                    + hashlib.sha256(Path(file_owned_config).read_bytes()).hexdigest()
                )
            except OSError:
                return None
        return None
    revision = entry.get("revision")
    if not isinstance(revision, int) or revision < 1:
        return None
    canonical = json.dumps(
        {"value": entry.get("value", {}), "revision": revision},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()
