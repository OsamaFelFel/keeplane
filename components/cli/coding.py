"""Run a local coding turn with the signed-in account and requested project."""

import json
import uuid
from pathlib import Path
from urllib.parse import urlsplit

if __package__:
    from . import opencode_adapter
    from .credential_profile import ProfileError, opened
    from .project_registration import register
    from .server_connection import (ConnectionError, account, model_alternatives,
                                    model_choice, models, origin)
else:
    import opencode_adapter
    from credential_profile import ProfileError, opened
    from project_registration import register
    from server_connection import (ConnectionError, account, model_alternatives,
                                   model_choice, models, origin)


NO_MODELS = ("No models are available for this project yet, so nothing was sent. "
             "Ask an admin to add a model, or approve one for this project's class, "
             "in Models and routing.")

UNAVAILABLE = ("{requested} is approved for this project but can't be used right now, so "
               "nothing was sent. Choose another model allowed for this project, or ask "
               "an admin to check it in Models and routing.")

# Spec 004 ST16, owner decision of 31 October 2026: the gateway has already
# retried a model that is down; Keeplane never switches it, it tells the developer.
STOPPED = {
    "down": "{model} is unavailable right now, so this task stopped. ",
    "too_big": "This task is too big for {model}'s context, so it stopped. ",
}
SWITCH = {
    "down": "Wait and try again, or run it with another model allowed for this project",
    "too_big": "Run it with another model allowed for this project",
}
WAIT = {"down": "Wait and try again. ", "too_big": ""}
CONTEXT_SIGNS = ("context_length_exceeded", "maximum context length", "context window",
                 "contextoverflow", "prompt is too long", "too many tokens")

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


def _walk(value, depth=0):
    """Yield (key, value) pairs of a decoded error event, bounded in depth."""
    if depth > 8:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from _walk(item, depth + 1)
    elif isinstance(value, list):
        for item in value[:64]:
            yield from _walk(item, depth + 1)


def model_problem(stdout):
    """Return "down", "too_big" or None for the runtime's error events.

    The gateway has already retried a model that is down: a 429 or 5xx that
    remains is final. A context-length refusal is never retried.
    """
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "error":
            continue
        statuses, text = set(), []
        for key, value in _walk(event):
            if key in ("statusCode", "status") and type(value) is int:
                statuses.add(value)
            elif isinstance(value, str):
                text.append(value.lower())
        text = " ".join(text).replace(" ", "")
        if any(sign.replace(" ", "") in text for sign in CONTEXT_SIGNS):
            return "too_big"
        if any(status == 429 or 500 <= status <= 599 for status in statuses):
            return "down"
    return None


def problem_message(problem, model, alternatives):
    """Tell the developer what happened and which allowed models they may choose."""
    message = STOPPED[problem].format(model=model)
    if alternatives is None:
        return (message + SWITCH[problem]
                + " using --model; `keeplane models` lists them.")
    if not alternatives:
        return message + WAIT[problem] + NO_MODELS
    return message + SWITCH[problem] + " using --model: " + ", ".join(alternatives) + "."


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
        problem = model_problem(result.stdout) if result.returncode else None
        if problem:
            try:
                alternatives = model_alternatives(
                    credential.issuer, project_id, model, credential.access_token)
            except ConnectionError:
                alternatives = None  # An older server: the developer still gets the reason.
            result.stderr += problem_message(problem, model, alternatives) + "\n"
        for secret in secrets:
            result.stdout = result.stdout.replace(secret, "[redacted]")
            result.stderr = result.stderr.replace(secret, "[redacted]")
        return result
