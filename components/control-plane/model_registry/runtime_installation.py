"""Install the fixed managed runtime guard after an operator starts a fresh gateway."""

import fcntl
import json
import os
import stat
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener

from common.storage import storage_service
from integrations.gateway.applied import (
    MAX_APPLIED_BYTES,
    NoRedirect,
    applied_fingerprint,
)
from integrations.gateway.runtime_config import (
    RuntimeInstallationUnavailable,
    model_backends,
    overlay,
)
from integrations.gateway.runtime_readback import (
    require_applied_models,
    require_applied_overlay,
)

from .fingerprints import fingerprint
from .installed_runtime import (
    MODEL_ID,
    DjangoInstalledRuntimeGate,
    digest,
    unique_pairs,
)
from .models import ModelApproval
from .provider_keys import managed_key_digest


def atomic_private(path, value):
    descriptor, temporary = tempfile.mkstemp(prefix=".guard-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(
                json.dumps(
                    value, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode()
            )
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def local_applied():
    """The installer runs in the gateway network namespace; admin stays loopback."""
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open("http://127.0.0.1:15000/config_dump", timeout=3) as response:
            if (
                response.status != 200
                or response.headers.get_content_type() != "application/json"
            ):
                raise ValueError()
            raw = response.read(MAX_APPLIED_BYTES + 1)
        if len(raw) > MAX_APPLIED_BYTES:
            raise ValueError()
        value = json.loads(raw, object_pairs_hook=unique_pairs)
        applied_fingerprint(value)
        return value
    except HTTPError as error:
        error.close()
        raise RuntimeInstallationUnavailable(
            "The applied gateway is unavailable"
        ) from None
    except (OSError, ValueError, TypeError, RecursionError):
        raise RuntimeInstallationUnavailable(
            "The applied gateway is unavailable"
        ) from None


@storage_service
class DjangoRuntimeInstallation:
    def __init__(
        self,
        gateway,
        directory,
        trusted_file,
        key_directory,
        *,
        gateway_mode="managed",
        callback_host="app:3000",
        read_applied=local_applied,
    ):
        self.gateway, self.directory, self.trusted_file, self.key_directory = (
            gateway,
            Path(directory),
            Path(trusted_file),
            key_directory,
        )
        self.gateway_mode, self.callback_host, self.read_applied = (
            gateway_mode,
            callback_host,
            read_applied,
        )

    def _read(self, path):
        status, value = self.gateway.request(path, timeout=5, connection_retries=0)
        if status != 200 or not isinstance(value, dict):
            raise RuntimeInstallationUnavailable("Runtime management is unavailable")
        return value

    def _models(self, identifiers, resources):
        result = {}
        for identifier in identifiers:
            approval = ModelApproval.objects.filter(pk=identifier).first()
            row = next((row for row in resources if row.get("id") == identifier), None)
            if (
                approval is None
                or row is None
                or approval.key_choice not in ("none", "shared", "personal")
            ):
                raise RuntimeInstallationUnavailable(
                    "Choose a current approved supported model"
                )
            key_name, key_digest = "", ""
            if approval.key_choice == "shared":
                try:
                    path = row["value"]["auth"]["key"]["value"]["file"]
                except (KeyError, TypeError):
                    raise RuntimeInstallationUnavailable(
                        "The shared key is unavailable"
                    ) from None
                if not isinstance(path, str):
                    raise RuntimeInstallationUnavailable(
                        "The shared key is unavailable"
                    )
                key_name, key_digest = (
                    Path(path).name,
                    managed_key_digest(self.key_directory, path),
                )
                if not key_digest:
                    raise RuntimeInstallationUnavailable(
                        "The shared key is unavailable"
                    )
            result[identifier] = {
                "fingerprint": fingerprint(identifier, resources),
                "key_choice": approval.key_choice,
                "key_name": key_name,
                "key_digest": key_digest,
            }
        return result

    def install(self, identifiers):
        if (
            self.gateway_mode != "managed"
            or self.gateway.base_url != "http://127.0.0.1:4000"
        ):
            raise RuntimeInstallationUnavailable("Use the managed gateway installer")
        if not self.directory.is_absolute() or not self.trusted_file.is_absolute():
            raise RuntimeInstallationUnavailable(
                "Private installation paths are required"
            )
        metadata = self.directory.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid not in (0, os.geteuid())
            or metadata.st_mode & 0o077
        ):
            raise RuntimeInstallationUnavailable(
                "The installation directory must be private"
            )
        descriptor = os.open(
            self.directory / ".installation.lock",
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
        )
        try:
            lock = os.fstat(descriptor)
            if (
                not stat.S_ISREG(lock.st_mode)
                or lock.st_uid not in (0, os.geteuid())
                or lock.st_mode & 0o077
            ):
                raise RuntimeInstallationUnavailable(
                    "The installation lock must be private"
                )
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return self._install(identifiers)
        finally:
            os.close(descriptor)

    def _install(self, identifiers):
        active = self.directory / "manifest.json"
        atomic_private(active, {"version": 2, "enabled": False})
        if (
            not 1 <= len(identifiers) <= 32
            or len(set(identifiers)) != len(identifiers)
            or any(not MODEL_ID.fullmatch(identifier) for identifier in identifiers)
        ):
            raise RuntimeInstallationUnavailable("Declare up to 32 exact model IDs")
        config_file = self.directory / "gateway.json"
        with self.trusted_file.open("rb") as source:
            trusted_bytes = source.read(MAX_APPLIED_BYTES + 1)
        if len(trusted_bytes) > MAX_APPLIED_BYTES:
            raise RuntimeInstallationUnavailable("The trusted base is too large")
        try:
            trusted = json.loads(trusted_bytes, object_pairs_hook=unique_pairs)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            raise RuntimeInstallationUnavailable(
                "The trusted base is malformed"
            ) from None
        if not isinstance(trusted, dict) or config_file.read_bytes() != trusted_bytes:
            raise RuntimeInstallationUnavailable(
                "Start a fresh gateway with the trusted base first"
            )
        base = self._read("/api/config")
        if digest(base) != digest(trusted):
            raise RuntimeInstallationUnavailable(
                "The loaded base differs from the trusted file"
            )
        initial = self.read_applied()
        if any(bind["key"] == "bind/5000" for bind in initial["binds"]):
            raise RuntimeInstallationUnavailable(
                "Start a fresh gateway before enrollment"
            )
        resources = self._read("/api/config/resources")["resources"]
        if any(row.get("kind") != "llm.model" for row in resources):
            raise RuntimeInstallationUnavailable(
                "This fixed installation supports model resources only"
            )
        file_models = {row["name"] for row in base.get("llm", {}).get("models", [])}
        if file_models & set(identifiers):
            raise RuntimeInstallationUnavailable("File-owned models cannot be enrolled")
        expected = deepcopy(base)
        expected["llm"]["models"].extend(deepcopy([row["value"] for row in resources]))
        if digest(self._read("/api/config/effective")) != digest(expected):
            raise RuntimeInstallationUnavailable(
                "The complete desired baseline changed"
            )
        models = self._models(identifiers, resources)
        gate = DjangoInstalledRuntimeGate(self.gateway, str(active), self.key_directory)
        for identifier, model in models.items():
            gate.require_definition(identifier, model)
        targets = model_backends(initial, identifiers)
        generated = overlay(base, models, targets, callback_host=self.callback_host)
        expected = deepcopy(generated)
        expected["llm"]["models"].extend(deepcopy([row["value"] for row in resources]))
        atomic_private(config_file, generated)
        deadline = time.monotonic() + 15
        while True:
            try:
                applied = self.read_applied()
                require_applied_overlay(applied, generated, models, targets)
                require_applied_models(applied, resources, models, targets)
                break
            except (RuntimeInstallationUnavailable, KeyError, TypeError, StopIteration):
                if time.monotonic() >= deadline:
                    raise RuntimeInstallationUnavailable(
                        "The complete guard has not applied"
                    ) from None
                time.sleep(0.1)
        if digest(self._read("/api/config")) != digest(generated) or digest(
            self._read("/api/config/effective")
        ) != digest(expected):
            raise RuntimeInstallationUnavailable(
                "The published desired topology changed"
            )
        declaration = {
            "version": 2,
            "enabled": True,
            "file_digest": digest(generated),
            "effective_digest": digest(expected),
            "applied_digest": applied_fingerprint(applied),
            "models": models,
        }
        candidate = self.directory / "candidate.json"
        atomic_private(candidate, declaration)
        final = DjangoInstalledRuntimeGate(
            self.gateway, str(candidate), self.key_directory
        )
        for identifier in identifiers:
            final.require_installed(identifier)
        try:
            atomic_private(active, declaration)
        except OSError:
            # replace() can succeed before fsync(directory) fails. Do not leave
            # an unconfirmed enabled file without attempting to disable it.
            try:
                atomic_private(active, {"version": 2, "enabled": False})
            except OSError:
                pass
            raise RuntimeInstallationUnavailable(
                "Enrollment did not complete; access state could not be confirmed"
            ) from None
        finally:
            try:
                candidate.unlink(missing_ok=True)
            except OSError:
                pass  # An unused private candidate is not inference authority.
        return {"models": list(identifiers)}
