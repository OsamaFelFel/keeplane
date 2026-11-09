"""Run a local coding turn with the signed-in account in the current repo's project."""

import json
import shutil
from pathlib import Path
from urllib.parse import urlsplit

if __package__:
    from . import opencode_adapter, project_identity, settings_file, usage
    from .credential_profile import ProfileError, opened
    from .project_registration import register
    from .server_connection import (
        ConnectionError,
        SignInExpired,
        account,
        model_alternatives,
        model_choice,
        models,
        origin,
        request,
    )
else:
    import opencode_adapter
    import project_identity
    import settings_file
    import usage
    from credential_profile import ProfileError, opened
    from project_registration import register
    from server_connection import (
        ConnectionError,
        SignInExpired,
        account,
        model_alternatives,
        model_choice,
        models,
        origin,
        request,
    )


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
# Owner decision on governance issue #52: the task was sent and failed, so the
# ST12 "nothing was sent" message is not used when no other model is allowed.
NO_OTHER_MODEL = {
    "down": ("{model} is unavailable right now and no other model is allowed for "
             "this project. Wait and try again, or ask your admin to set up "
             "another model."),
    # Product decision on governance issue #57: same pattern as #52.
    "too_big": ("This task is too big for {model}'s context and no other model is "
                "allowed for this project. Make the task smaller, or ask your admin "
                "to set up a model with a larger context."),
}
CONTEXT_SIGNS = ("context_length_exceeded", "maximum context length", "context window",
                 "contextoverflow", "prompt is too long", "too many tokens")

REASONS = {
    "missing": "No provider key is added for {requested}",
    "refused": "The provider refused your key for {requested}",
    "outdated": "Your provider key for {requested} was saved for an earlier model setup",
}


NO_GATEWAY = ("Keeplane doesn't know your gateway address yet, so nothing was sent. "
              "Pass --gateway with the address your admin gave you, ending in /v1.")

NO_ROUTED_MODEL = ("None of the models allowed for this project can be used right now, "
                   "so nothing was sent. Choose one with --model; `keeplane models` "
                   "lists them.")

NO_RUNTIME = ("Keeplane can't find OpenCode V2 " + opencode_adapter.VERSION + ". Install "
              "it, then put `opencode` on your PATH, pass --runtime PATH, or set "
              '"runtime" in your Keeplane settings file.')

WRONG_RUNTIME = ("Keeplane needs OpenCode V2 " + opencode_adapter.VERSION + ", and {path} "
                 "is another version or doesn't run. Install " + opencode_adapter.VERSION
                 + ", then put it on your PATH, pass --runtime PATH, or set \"runtime\" in your "
                 "Keeplane settings file.")

TASK_MODEL_FIELDS = {"project_id", "requested_model_id", "persona", "level",
                     "model_id", "chosen_by", "reason"}


def find_runtime(given=None):
    """OpenCode from --runtime, then the settings file, then PATH (ADR 030).

    The adapter checks the exact version before every turn.
    """
    if given:
        return str(Path(given).expanduser())
    try:
        saved = settings_file.runtime()
    except settings_file.SettingsError as error:
        raise ConnectionError(str(error)) from None
    if saved:
        return saved
    found = shutil.which("opencode")
    if found is None:
        raise ConnectionError(NO_RUNTIME)
    return found


def task_model(issuer, project_id, credential):
    """Ask the server which allowed model a task with no --model goes to."""
    body = request(issuer, "/api/runtime/projects/" + project_id + "/task-model",
                   credential)
    try:
        data = json.loads(body)
        if (not isinstance(data, dict) or set(data) != TASK_MODEL_FIELDS
                or data["project_id"] != project_id
                or data["requested_model_id"] is not None
                or (data["model_id"] is not None and (
                    not isinstance(data["model_id"], str)
                    or not 0 < len(data["model_id"]) <= 256
                    or any(ord(c) < 32 or ord(c) == 127 for c in data["model_id"])))):
            raise ValueError
    except (ValueError, UnicodeError, RecursionError):
        raise ConnectionError("The server returned an invalid model choice.") from None
    return data["model_id"]


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


def _events(stdout):
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def gateway_refused_sign_in(stdout):
    """None, or whether earlier steps went out before the gateway said 401.

    The runtime prints an event only once a model step has started, so any event
    before the 401 error means part of the task had already been sent.
    """
    earlier = False
    for event in _events(stdout):
        if event.get("type") == "error":
            if any(key in ("statusCode", "status") and type(value) is int and value == 401
                   for key, value in _walk(event)):
                return earlier
        else:
            earlier = True
    return None


def model_problem(stdout):
    """Return "down", "too_big" or None for the runtime's error events.

    The gateway has already retried a model that is down: a 429 or 5xx that
    remains is final. A context-length refusal is never retried.
    """
    for event in _events(stdout):
        if event.get("type") != "error":
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
        return NO_OTHER_MODEL[problem].format(model=model)
    return message + SWITCH[problem] + " using --model: " + ", ".join(alternatives) + "."


def gateway_endpoint(value):
    url = urlsplit(value)
    if url.path.rstrip("/") != "/v1" or url.query or url.fragment:
        raise ConnectionError("Use the operator's protected gateway URL ending in /v1.")
    return origin(value[:len(value) - len(url.path)]) + "/v1"


def run(profile_path, project_id, name, model, binary, directory, gateway, prompt,
        timeout=300, *, cancelled=None, instructions=(), state_dir=None, session=None,
        notify=None):
    """One coding turn. Only the profile and prompt are needed (Spec 009 ST30).

    The project comes from the repo, the gateway from the profile, the model
    from the server's task-model route and the runtime from the settings file
    or PATH; each given value overrides.
    """
    if gateway is not None:
        gateway = gateway_endpoint(gateway)
    directory = Path(directory).expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("Choose a working repository directory.")
    project = project_identity.resolve(directory, project_id, name)
    project_id = project.id
    binary = find_runtime(binary)
    with opened(profile_path) as profile:
        credential = profile.load()
        if gateway is None:
            # The address the server gave at sign-in (task 009-02), once saved.
            saved = getattr(credential, "gateway", None)
            if not saved:
                raise ConnectionError(NO_GATEWAY)
            gateway = gateway_endpoint(saved)
        actor = account(credential.issuer, credential.access_token)
        if actor["id"] != credential.actor_id:
            raise ProfileError("The server account changed; sign in again.")
        register(credential.issuer, project_id, project.name, credential.access_token)
        catalog = models(credential.issuer, project_id, credential.access_token)
        if not catalog["models"]:
            raise ConnectionError(NO_MODELS)
        allowed = {row["id"] for row in catalog["models"]}
        secrets = (credential.access_token, credential.refresh_token)

        def report(message):
            for secret in secrets:
                message = message.replace(secret, "[redacted]")
            if notify:
                notify(message)

        if model is None:
            try:
                model = task_model(credential.issuer, project_id, credential.access_token)
            except ConnectionError as error:
                if error.status == 404:  # An older server has no task-model route.
                    raise ConnectionError(NO_ROUTED_MODEL, 404) from None
                raise
            if model is None:
                raise ConnectionError(NO_ROUTED_MODEL)
            if model not in allowed:
                raise ConnectionError("This model is not currently allowed for the project.")
            report("Using " + model + " for this task, chosen by Keeplane. "
                   "Pass --model to choose another.")
        else:
            if model not in allowed:
                raise ConnectionError("This model is not currently allowed for the project.")
            model = chosen_model(credential.issuer, project_id, model,
                                 credential.access_token, report)
            if model not in allowed:
                raise ConnectionError("This model is not currently allowed for the project.")
        try:
            result = opencode_adapter.run(
                binary, directory, gateway, model, prompt, credential.access_token,
                timeout, cancelled=cancelled, instructions=instructions,
                state_dir=state_dir, session=session,
                account_context={"issuer": credential.issuer, "actor_id": actor["id"],
                                 "project_id": project_id},
            )
        except (FileNotFoundError, PermissionError):
            raise ConnectionError(WRONG_RUNTIME.format(path=binary)) from None
        except ValueError as error:
            # The adapter's exact-version check; other ValueErrors stay generic.
            if str(error).startswith("This prototype requires OpenCode V2"):
                raise ConnectionError(WRONG_RUNTIME.format(path=binary)) from None
            raise
        refused = gateway_refused_sign_in(result.stdout) if result.returncode else None
        if refused is not None:
            # ST29: the gateway refused the sign-in; nothing more is sent, not even
            # a request for other models.
            for secret in secrets:
                result.stdout = result.stdout.replace(secret, "[redacted]")
                result.stderr = result.stderr.replace(secret, "[redacted]")
            raise SignInExpired(more=refused, result=result)
        problem = model_problem(result.stdout) if result.returncode else None
        if problem:
            try:
                alternatives = model_alternatives(
                    credential.issuer, project_id, model, credential.access_token)
            except ConnectionError:
                alternatives = None  # An older server: the developer still gets the reason.
            result.stderr += problem_message(problem, model, alternatives) + "\n"
        # ADR 029: one usage report per model, from the gateway's answers.
        result.stderr += usage.report_turn(credential.issuer, project_id,
                                           credential.access_token,
                                           getattr(result, "usage", None))
        for secret in secrets:
            result.stdout = result.stdout.replace(secret, "[redacted]")
            result.stderr = result.stderr.replace(secret, "[redacted]")
        return result
