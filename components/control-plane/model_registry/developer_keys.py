"""Internal owner-scoped key storage; no HTTP admission or dispatch selection."""

from pathlib import Path

from accounts.models import User
from common.errors import StorageUnavailable
from common.storage import storage_service
from django.db import DatabaseError, transaction
from integrations.gateway.keys import KEY_NAME, remove, save

from .key_validation import ProviderKeyRefused, VerifiedProviderKey
from .models import DeveloperProviderKey
from .provider_keys import managed_key_available


class DeveloperKeyError(Exception):
    pass


class DeveloperKeyRefused(DeveloperKeyError):
    pass


class DeveloperKeyUnverified(DeveloperKeyError):
    pass


@storage_service
class DjangoDeveloperKeyStore:
    def __init__(self, owner_id, directory, *, validate_key, reauthenticate=None):
        if not callable(validate_key) or not callable(
            getattr(validate_key, "require_current", None)
        ):
            raise DeveloperKeyError("Configure a server provider-key validator")
        if not directory or not Path(directory).is_absolute():
            raise StorageUnavailable("Provider key storage is unavailable")
        if reauthenticate is not None and not callable(reauthenticate):
            raise DeveloperKeyError("Configure current runtime authentication")
        self.reauthenticate = reauthenticate
        self.owner_id, self.directory = owner_id, directory
        self.validate_key = validate_key

    def _owner(self, lock=False, active=True):
        owners = User.objects.select_for_update() if lock else User.objects
        owners = owners.filter(pk=self.owner_id)
        owner = owners.first()
        if lock and active and self.reauthenticate:
            self.reauthenticate(owner)
        if owner is None or (active and not owner.is_active):
            raise DeveloperKeyError("This account is unavailable")
        return owner

    def _model(self, model_id):
        if not isinstance(model_id, str) or not 0 < len(model_id) <= 256:
            raise DeveloperKeyError("Choose a model")
        return model_id

    def _path(self, name):
        if not KEY_NAME.fullmatch(name):
            raise StorageUnavailable("Provider key metadata is unavailable")
        return str(Path(self.directory) / name)

    def _remove(self, name):
        path = self._path(name)
        try:
            return remove(self.directory, path) or not Path(path).exists()
        except OSError:
            return False

    def _drain(self, row):
        if row.pending_key_name:
            if not self._remove(row.pending_key_name):
                return False
            row.pending_key_name = ""
            row.save(update_fields=["pending_key_name"])
        return True

    def _status(self, model_id, row, *, registration_only=False):
        present = bool(row and row.key_name)
        if present and not registration_only and not row.validation_fingerprint:
            raise StorageUnavailable("This provider key requires validation")
        if present and not registration_only and not managed_key_available(self.directory, self._path(row.key_name)):
            raise StorageUnavailable("Provider key file is unavailable")
        return {"model_id": model_id, "status": "added" if present else "missing",
                "cleanup_pending": bool(row and row.pending_key_name)}

    def status(self, model_id, *, registration_only=False):
        model_id = self._model(model_id)
        with transaction.atomic():
            self._owner(lock=True)
            row = DeveloperProviderKey.objects.filter(owner_id=self.owner_id, model_id=model_id).first()
            return self._status(model_id, row, registration_only=registration_only)

    def _finish(self, model_id):
        try:
            with transaction.atomic(durable=True):
                owner = self._owner(lock=True, active=False)
                row = DeveloperProviderKey.objects.filter(owner=owner, model_id=model_id).first()
                if row:
                    self._drain(row)
                    if not row.key_name and not row.pending_key_name:
                        row.delete()
                        row = None
                return self._status(model_id, row)
        except DatabaseError:
            raise StorageUnavailable("Key state changed; cleanup status is unavailable") from None

    def _validate(self, model_id, value):
        try:
            accepted = self.validate_key(str(self.owner_id), model_id, value)
        except ProviderKeyRefused:
            raise DeveloperKeyRefused("The provider refused the key") from None
        except Exception:
            raise DeveloperKeyUnverified("The provider key could not be checked") from None
        if (
            not isinstance(accepted, VerifiedProviderKey)
            or accepted.owner_id != str(self.owner_id)
            or accepted.model_id != model_id
            or not isinstance(accepted.definition_fingerprint, str)
            or len(accepted.definition_fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in accepted.definition_fingerprint)
        ):
            raise DeveloperKeyUnverified("The provider key could not be checked")
        return accepted

    def put(self, model_id, value):
        """Add/replace only after server-issued, definition-bound verification.

        The owner lock covers current runtime authentication, provider validation
        and storage. Runtime callers must configure the authentication recheck.
        """
        model_id = self._model(model_id)
        try:
            valid = (isinstance(value, str) and 12 <= len(value) <= 512 and value == value.strip()
                     and all(byte >= 32 and byte != 127 for byte in value.encode("utf-8")))
        except UnicodeError:
            valid = False
        if not valid:
            raise DeveloperKeyError("Enter a valid provider key")
        new_name = None
        try:
            # Own the commit: nested caller transactions cannot later roll it back
            # after the file lifecycle has advanced. User locks serialize writers.
            with transaction.atomic(durable=True):
                owner = self._owner(lock=True)
                accepted = self._validate(model_id, value)
                try:
                    self.validate_key.require_current(accepted)
                except Exception:
                    raise DeveloperKeyUnverified(
                        "The current model could not be verified; check the key again"
                    ) from None
                row, _ = DeveloperProviderKey.objects.get_or_create(owner=owner, model_id=model_id)
                if not self._drain(row):
                    raise StorageUnavailable("Previous provider key cleanup is pending")
                new_name = Path(save(self.directory, value)).name
                row.pending_key_name, row.key_name = row.key_name, new_name
                row.validation_fingerprint = accepted.definition_fingerprint
                row.save(
                    update_fields=["key_name", "pending_key_name", "validation_fingerprint"]
                )
        except BaseException as error:
            if new_name and not self._remove(new_name):
                raise StorageUnavailable("The key was not saved; temporary-key cleanup failed") from None
            if isinstance(error, OSError):
                raise StorageUnavailable("Provider key file storage is unavailable") from None
            raise
        return self._finish(model_id)

    def remove(self, model_id):
        model_id = self._model(model_id)
        with transaction.atomic(durable=True):
            owner = self._owner(lock=True)
            row = DeveloperProviderKey.objects.filter(owner=owner, model_id=model_id).first()
            if row:
                if not self._drain(row):
                    raise StorageUnavailable("Previous provider key cleanup is pending")
                row.pending_key_name, row.key_name = row.key_name, ""
                row.save(update_fields=["key_name", "pending_key_name"])
        return self._finish(model_id)
