"""Manage one account's server-held provider keys without storing them locally."""

import getpass
import json
import sys
import uuid
import warnings

if __package__:
    from .credential_profile import ProfileError, opened
    from .project_registration import register
    from .server_connection import ConnectionError, account, request
else:
    from credential_profile import ProfileError, opened
    from project_registration import register
    from server_connection import ConnectionError, account, request


# The server's refusal of `keys set` when Keeplane uses a customer-run gateway
# (Spec 004 D110): no key can be used there, so none is saved. The CLI asks
# first (own_keys_supported) and this refusal is the server's backstop.
OWN_KEYS_UNSUPPORTED = (
    "Keeplane can't pass developers' own keys to a gateway it doesn't run yet, "
    "so use No key for this model."
)


def own_keys_unsupported(model_id):
    return (
        f"Keeplane can't use developers' own keys with this installation's gateway, "
        f"so your key for {model_id} wasn't saved. Ask your Keeplane admin which "
        "models you can use."
    )


def own_keys_supported(issuer, access_token):
    """Ask the server whether it can use developers' own keys, before any prompt.

    A server from before this check answers 404; it is asked nothing more and
    its PUT decides, as before.
    """
    try:
        body = request(issuer, "/api/runtime/provider-keys/support", access_token)
    except ConnectionError as error:
        if error.status == 404:
            return True
        raise
    try:
        data = json.loads(body, object_pairs_hook=unique)
        if (
            len(body) > 4096
            or not isinstance(data, dict)
            or set(data) != {"own_keys"}
            or type(data["own_keys"]) is not bool
        ):
            raise ValueError
    except (ValueError, TypeError, RecursionError):
        raise ConnectionError("Keeplane returned an invalid key answer.") from None
    return data["own_keys"]


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


def project_id_of(project_id):
    try:
        return str(uuid.UUID(str(project_id)))
    except (ValueError, TypeError, AttributeError):
        raise ConnectionError("Use a valid project UUID.") from None


def key_rows(issuer, access_token, project_id):
    """The project's allowed models and this account's key states; no provider call."""
    body = request(
        issuer,
        "/api/runtime/projects/" + project_id + "/provider-keys",
        access_token,
    )
    try:
        data = json.loads(body, object_pairs_hook=unique)
        if (
            not isinstance(data, dict)
            or set(data) != {"project_id", "models"}
            or data["project_id"] != project_id
            or not isinstance(data["models"], list)
        ):
            raise ValueError
        ids = []
        for row in data["models"]:
            if (
                not isinstance(row, dict)
                or set(row) != {"id", "own_key_required", "status"}
                or not isinstance(row["id"], str)
                or not 0 < len(row["id"]) <= 256
                or any(ord(c) < 32 or ord(c) == 127 for c in row["id"])
                or type(row["own_key_required"]) is not bool
                or (
                    row["own_key_required"]
                    and row["status"] not in {"added", "missing", "refused"}
                )
                or (not row["own_key_required"] and row["status"] is not None)
            ):
                raise ValueError
            ids.append(row["id"])
        if ids != sorted(set(ids)):
            raise ValueError
    except (ValueError, TypeError, RecursionError):
        raise ConnectionError("Keeplane returned an invalid key list.") from None
    return data


def list_keys(profile_path, project_id, name=None):
    project_id = project_id_of(project_id)
    with opened(profile_path) as profile:
        credential = profile.load()
        actor = account(credential.issuer, credential.access_token)
        if actor["id"] != credential.actor_id:
            raise ProfileError("The server account changed; sign in again.")
        if name:
            # Any repo works with no setup (D149): record it as `code` does.
            register(credential.issuer, project_id, name, credential.access_token)
        data = key_rows(credential.issuer, credential.access_token, project_id)
        output = json.dumps(data, indent=2)
        for secret in (credential.access_token, credential.refresh_token):
            output = output.replace(secret, "[redacted]")
        return output


def key_status(body, model_id, action):
    try:
        data = json.loads(body, object_pairs_hook=unique)
        if (
            len(body) > 4096
            or not isinstance(data, dict)
            or set(data) != {"model_id", "status", "cleanup_pending"}
            or data["model_id"] != model_id
            or data["status"] not in {"added", "missing", "refused"}
            or type(data["cleanup_pending"]) is not bool
            or (action == "set" and data["status"] != "added")
            or (action == "remove" and data["status"] != "missing")
        ):
            raise ValueError
    except (ValueError, TypeError, RecursionError):
        raise ConnectionError("Keeplane returned invalid key status.") from None
    return data


def refused_after_failure(issuer, access_token, project_id, model_id):
    """Spec 004 ST11 (ADR 030): did a task's 401 or 403 come from a refused own key?

    Called after a coding task failed with a 401 or 403. The key list (no
    provider call) says whether ``model_id`` uses the developer's own key and
    whether one is saved; only then does the server recheck that saved key with
    the provider and record its verdict, which ``keys list`` then shows. True
    when the server now records the key as refused. Any other answer, including
    an expired sign-in or an older server, is False: the task's own error stands.
    """
    try:
        project_id = project_id_of(project_id)
        rows = key_rows(issuer, access_token, project_id)["models"]
        row = next((row for row in rows if row["id"] == model_id), None)
        if row is None or not row["own_key_required"] or row["status"] == "missing":
            return False
        if row["status"] == "refused":
            return True
        body = request(
            issuer,
            "/api/runtime/provider-keys/check",
            access_token,
            method="POST",
            payload={"model_id": model_id},
        )
        return key_status(body, model_id, "check")["status"] == "refused"
    except ConnectionError:
        return False


def run(action, profile_path, model_id, *, key_stdin=False):
    if action not in {"set", "status", "check", "remove"} or (key_stdin and action != "set"):
        raise ConnectionError("Choose keys set, status, check or remove.")
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
        if action == "set" and not own_keys_supported(
            credential.issuer, credential.access_token
        ):
            raise ConnectionError(own_keys_unsupported(model_id), 403)
        key = read_key(key_stdin=key_stdin) if action == "set" else None
        if key is not None and key in {
            credential.access_token,
            credential.refresh_token,
        }:
            raise ConnectionError("Enter the model provider's key.")
        try:
            body = request(
                credential.issuer,
                "/api/runtime/provider-keys" + ("/check" if action == "check" else ""),
                credential.access_token,
                method={"set": "PUT", "status": "GET", "check": "POST", "remove": "DELETE"}[action],
                payload=None
                if action == "status"
                else {
                    "model_id": model_id,
                    **({"key": key} if key is not None else {}),
                },
                query={"model_id": model_id} if action == "status" else None,
            )
            data = key_status(body, model_id, action)
        except ConnectionError as error:
            if (
                action == "set"
                and error.status == 403
                and error.detail == OWN_KEYS_UNSUPPORTED
            ):
                raise ConnectionError(own_keys_unsupported(model_id), 403) from None
            if action in {"set", "remove"} and error.status not in {400, 401, 403, 413, 415}:
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
