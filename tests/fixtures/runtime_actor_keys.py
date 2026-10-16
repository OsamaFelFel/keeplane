"""Synthetic per-actor key injection; never a production key store or issuer."""

import json
import secrets
import uuid

PATH = "/fixture/actor-key-authorize"
STRIP_HEADERS = ("x-api-key", "x-provider-authorization", "x-keeplane-actor-id")


def actors(state):
    return json.loads((state / "actors").read_text())


def key_file(state, actor):
    return state / actor["key_file"]


def change_key(state, label, remove=False):
    path = key_file(state, actors(state)[label])
    if remove:
        path.unlink(missing_ok=True)
    else:
        path.write_text(secrets.token_urlsafe(32))
        path.chmod(0o600)


def seed(state, identity, token, project):
    password = "isolated-second-actor-password"
    second = identity.create_user(
        {"username": "runtime-second", "password": password, "role": "developer"}
    )
    second_token = identity.login(second["username"], password)
    rows = {
        "a": {"actor_id": identity.session(token)["id"], "token": token},
        "b": {"actor_id": second["id"], "token": second_token},
    }
    for label, actor in rows.items():
        actor["key_file"] = "actor-" + uuid.uuid4().hex
        credential = state / ("credential-" + label)
        credential.write_text(json.dumps({"token": actor["token"], "project": project}))
        credential.chmod(0o600)
    path = state / "actors"
    path.write_text(json.dumps(rows))
    path.chmod(0o600)
    change_key(state, "a")  # B starts without a provider key.


def provider_identity(state, authorization):
    rows = actors(state)
    label = next(
        (
            label
            for label, actor in rows.items()
            if key_file(state, actor).is_file()
            and authorization == "Bearer " + key_file(state, actor).read_text()
        ),
        None,
    )
    return label, any(actor["token"] in authorization for actor in rows.values())


def wrap(application, state):
    def authorized(environ, start_response):
        if environ["PATH_INFO"] != PATH:
            return application(environ, start_response)
        environ["PATH_INFO"] = "/internal/runtime/authorize"
        response = []

        def capture(status, headers, exc_info=None):
            response[:] = [status, headers]

        result = application(environ, capture)
        try:
            body = b"".join(result)
        finally:
            if hasattr(result, "close"):
                result.close()
        status, headers = response
        if status.startswith("200 "):
            actor_id = json.loads(body)["actor_id"]
            selected = next(
                (
                    actor
                    for actor in actors(state).values()
                    if actor["actor_id"] == actor_id
                ),
                None,
            )
            try:
                key = key_file(state, selected).read_text() if selected else ""
            except OSError:
                key = ""
            if not key:
                status, headers, body = "403 Forbidden", [("Content-Length", "0")], b""
            else:
                headers.append(("Authorization", "Bearer " + key))
        start_response(status, headers)
        return [body]

    return authorized
