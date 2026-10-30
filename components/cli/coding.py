"""Run a local coding turn with the signed-in account and requested project."""

import uuid
from pathlib import Path
from urllib.parse import urlsplit

if __package__:
    from . import opencode_adapter
    from .credential_profile import ProfileError, opened
    from .project_registration import register
    from .server_connection import ConnectionError, account, model_choice, models, origin
else:
    import opencode_adapter
    from credential_profile import ProfileError, opened
    from project_registration import register
    from server_connection import ConnectionError, account, model_choice, models, origin


NO_MODELS = ("No models are available for this project yet, so nothing was sent. "
             "Ask an admin to add a model, or approve one for this project's class, "
             "in Models and routing.")

UNAVAILABLE = ("{requested} is approved for this project but can't be used right now, so "
               "nothing was sent. Choose another model allowed for this project, or ask "
               "an admin to check it in Models and routing.")

REASONS = {
    "missing": "No provider key is added for {requested}",
    "refused": "The provider refused your key for {requested}",
    "outdated": "Your provider key for {requested} was saved for an earlier model setup",
}


def chosen_model(issuer, project_id, model, credential, notify):
    """Use another allowed model when the requested one needs the developer's key."""
    try:
        choice = model_choice(issuer, project_id, model, credential)
    except ConnectionError as error:
        if error.status == 404:
            return model  # An older server has no choice route; the gateway still checks.
        raise
    if choice["reason"] is None:
        return model
    if choice["reason"] == "unavailable":
        raise ConnectionError(UNAVAILABLE.format(requested=model), 503)
    why = REASONS[choice["reason"]].format(requested=model)
    fix = "keeplane keys set --model " + model
    action = "Add one" if choice["reason"] == "missing" else "Replace it"
    if choice["model_id"] is None:
        raise ConnectionError(
            "Add or replace your provider key: " + why
            + ", and no other allowed model is available for this project. Run `"
            + fix + "`.", 403)
    notify(why + "; using " + choice["model_id"] + " instead. " + action + " with `" + fix + "`.")
    return choice["model_id"]


def gateway_endpoint(value):
    url = urlsplit(value)
    if url.path.rstrip("/") != "/v1" or url.query or url.fragment:
        raise ConnectionError("Use the operator's protected gateway URL ending in /v1.")
    return origin(value[:len(value) - len(url.path)]) + "/v1"


def run(profile_path, project_id, name, model, binary, directory, gateway, prompt,
        timeout=300, *, cancelled=None, instructions=(), state_dir=None, session=None,
        notify=None):
    gateway = gateway_endpoint(gateway)
    directory = Path(directory).expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("Choose a working repository directory.")
    project_id = str(uuid.UUID(str(project_id)))
    with opened(profile_path) as profile:
        credential = profile.load()
        actor = account(credential.issuer, credential.access_token)
        if actor["id"] != credential.actor_id:
            raise ProfileError("The server account changed; sign in again.")
        register(credential.issuer, project_id, name, credential.access_token)
        catalog = models(credential.issuer, project_id, credential.access_token)
        if not catalog["models"]:
            raise ConnectionError(NO_MODELS)
        if model not in {row["id"] for row in catalog["models"]}:
            raise ConnectionError("This model is not currently allowed for the project.")
        secrets = (credential.access_token, credential.refresh_token)

        def report(message):
            for secret in secrets:
                message = message.replace(secret, "[redacted]")
            if notify:
                notify(message)

        model = chosen_model(credential.issuer, project_id, model, credential.access_token, report)
        if model not in {row["id"] for row in catalog["models"]}:
            raise ConnectionError("This model is not currently allowed for the project.")
        result = opencode_adapter.run(
            binary, directory, gateway, model, prompt, credential.access_token,
            timeout, cancelled=cancelled, instructions=instructions,
            state_dir=state_dir, session=session,
            account_context={"issuer": credential.issuer, "actor_id": actor["id"],
                             "project_id": project_id},
        )
        for secret in secrets:
            result.stdout = result.stdout.replace(secret, "[redacted]")
            result.stderr = result.stderr.replace(secret, "[redacted]")
        return result
