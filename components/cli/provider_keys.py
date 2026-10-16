"""Manage one account's server-held provider keys without storing them locally."""

import getpass
import json
import sys
import warnings

if __package__:
    from .credential_profile import ProfileError, opened
    from .server_connection import ConnectionError, account, request
else:
    from credential_profile import ProfileError, opened
    from server_connection import ConnectionError, account, request


def read_key(*, key_stdin=False):
    if key_stdin:
        if sys.stdin.isatty():
            raise ConnectionError(
                "Use the hidden prompt in a terminal; --key-stdin needs a pipe."
            )
        raw = sys.stdin.buffer.read(515)
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        elif raw.endswith(b"\n"):
            raw = raw[:-1]
        try:
            value = raw.decode("ascii")
        except UnicodeError:
            raise ConnectionError("Enter a valid provider key.") from None
    else:
        if not sys.stdin.isatty():
            raise ConnectionError(
                "Use a terminal for hidden input or pipe a key with --key-stdin."
            )
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                value = getpass.getpass("Provider key: ")
        except (getpass.GetPassWarning, EOFError):
            raise ConnectionError(
                "Cannot read hidden key input; use a private pipe with --key-stdin."
            ) from None
    if (
        not isinstance(value, str)
        or not 12 <= len(value) <= 512
        or any(not 33 <= ord(char) <= 126 for char in value)
    ):
        raise ConnectionError("Enter a valid provider key.")
    return value


def unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError
        result[name] = value
    return result


def run(action, profile_path, model_id, *, key_stdin=False):
    if action not in {"set", "status", "remove"} or (key_stdin and action != "set"):
        raise ConnectionError("Choose keys set, status or remove.")
    if (
        not isinstance(model_id, str)
        or not 0 < len(model_id) <= 256
        or any(ord(char) < 32 or ord(char) == 127 for char in model_id)
    ):
        raise ConnectionError("Choose a model.")
    with opened(profile_path) as profile:
        credential = profile.load()
        actor = account(credential.issuer, credential.access_token)
        if actor["id"] != credential.actor_id:
            raise ProfileError("The server account changed; sign in again.")
        key = read_key(key_stdin=key_stdin) if action == "set" else None
        try:
            body = request(
                credential.issuer,
                "/api/runtime/provider-keys",
                credential.access_token,
                method={"set": "PUT", "status": "GET", "remove": "DELETE"}[action],
                payload=None
                if action == "status"
                else {
                    "model_id": model_id,
                    **({"key": key} if key is not None else {}),
                },
                query={"model_id": model_id} if action == "status" else None,
            )
            try:
                data = json.loads(body, object_pairs_hook=unique)
                if (
                    len(body) > 4096
                    or not isinstance(data, dict)
                    or set(data) != {"model_id", "status", "cleanup_pending"}
                    or data["model_id"] != model_id
                    or data["status"] not in {"added", "missing"}
                    or type(data["cleanup_pending"]) is not bool
                    or (action == "set" and data["status"] != "added")
                    or (action == "remove" and data["status"] != "missing")
                ):
                    raise ValueError
            except (ValueError, TypeError, RecursionError):
                raise ConnectionError("Keeplane returned invalid key status.") from None
        except ConnectionError as error:
            if action != "status" and error.status not in {400, 401, 403, 413, 415}:
                raise ConnectionError(
                    "The key change may have completed. Check keys status before retrying.",
                    error.status,
                ) from None
            raise
        output = json.dumps(data, indent=2)
        for secret in (credential.access_token, credential.refresh_token, key):
            if secret:
                output = output.replace(secret, "[redacted]")
        return output
