"""Run a local coding turn with the signed-in account in the current repo's project."""

import json
import shutil
from pathlib import Path

if __package__:
    from . import (
        opencode_adapter,
        project_identity,
        provider_keys,
        settings_file,
        usage,
    )
    from .credential_profile import ProfileError, opened
    from .project_registration import register
    from .server_connection import (
        ConnectionError,
        KeeplaneUnavailable,
        SignInExpired,
        Unreachable,
        account,
        gateway_endpoint,
        model_alternatives,
        model_choice,
        models,
        request,
    )
else:
    import opencode_adapter
    import project_identity
    import provider_keys
    import settings_file
    import usage
    from credential_profile import ProfileError, opened
    from project_registration import register
    from server_connection import (
        ConnectionError,
        KeeplaneUnavailable,
        SignInExpired,
        Unreachable,
        account,
        gateway_endpoint,
        model_alternatives,
        model_choice,
        models,
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
# Wording decided by the associate product owner for task 009-07.
SWITCH = {
    "down": "Wait and try again, or run `keeplane use <model>` with another model "
            "allowed for this project",
    "too_big": "Make the task smaller, or run `keeplane use <model>` with another "
               "model allowed for this project",
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
# How providers and runners word a context-length refusal. The llama.cpp
# server, Keeplane's local runner, answers "request (N tokens) exceeds the
# available context size (M tokens), try increasing it" with the error type
# "exceed_context_size_error".
CONTEXT_SIGNS = ("context_length_exceeded", "maximum context length", "context window",
                 "contextoverflow", "prompt is too long", "too many tokens",
                 "exceeds the available context size", "exceed_context_size_error")

REASONS = {
    "missing": "No provider key is added for {requested}",
    "refused": "The provider refused your key for {requested}",
    "outdated": "Your provider key for {requested} was saved for an earlier model setup",
}


NO_GATEWAY = ("Keeplane doesn't know your gateway address yet, so nothing was sent. "
              "Pass --gateway with the address your admin gave you, ending in /v1.")

NO_ROUTED_MODEL = ("None of the models allowed for this project can be used right now, "
                   "so nothing was sent. Choose one with `keeplane use <model>`; "
                   "`keeplane models` lists them.")

# Spec 004 ST17 (D105, D150): which model a task uses, and which one answered.
# Wording decided by the associate product owner for task 009-07.
USING_PICK = ("Using {model} for this task, chosen by Keeplane. "
              "Run `keeplane use <model>` to choose another.")
USING_SWITCH = ("Using {model} for this task, as you chose with `keeplane use`. "
                "Run `keeplane use --auto` to let Keeplane choose.")
ANSWERED_BY = "Answered by {models}."
# A developer can't switch to a model the project doesn't allow (keeplane #178).
SWITCH_NOT_ALLOWED = ("You switched this repo to {model}, but it isn't allowed for this "
                      "project any more{sent}. Run `keeplane use <model>` with a model "
                      "`keeplane models` lists, or `keeplane use --auto` to let "
                      "Keeplane choose.")
NOTHING_SENT = ", so nothing was sent"
PROJECT_REFUSED = "Nothing was sent."
# The server's refusal of a model the project doesn't allow, as opposed to,
# for example, "This project is unavailable".
MODEL_REFUSED = "This model is not eligible for the project"
# The switch stays saved when the developer's own key can't be used for it.
OWN_KEY = {
    "missing": "is missing",
    "refused": "is refused",
    "outdated": "is out of date",
}
OWN_KEY_NO_OTHER = ("Your own key for {model} {state}, and no other allowed model is "
                    "available for this project. Run `keeplane keys list` to see your keys.")
SWITCH_UNAVAILABLE = ("{model} is approved for this project but can't be used right now. "
                      "Try again in a few minutes.")
UNMARKED = "Your `keeplane use` choice isn't shown in this list until the file is fixed."
OWN_KEY_MOVED = ("Your own key for {model} {state}, so {task} uses {other}. "
                 "Run `keeplane keys list` to see your keys.")

# 009-15 (ADR 028): an outage, not the model, stopped the turn. Either the
# gateway didn't answer, or it refused because Keeplane's check couldn't run
# (the app or its database down or restarting). The sign-in still works.
GATEWAY_DOWN = ("Keeplane's gateway can't be reached right now, so this task stopped "
                "and nothing {more}was sent. Try again in a few minutes, or ask your "
                "admin to check the gateway.")
# Wording decided by the associate product owner: `code` couldn't connect to
# Keeplane at all, or Keeplane said it is unavailable (502, 503 or 504),
# before the task started. A TLS or certificate problem keeps its own message.
START_UNAVAILABLE = ("Keeplane isn't available right now, so nothing was sent. Try "
                     "again in a few minutes, or ask your admin to check Keeplane.")
SERVER_DOWN = ("Keeplane isn't available right now, so this task stopped and nothing "
               "{more}was sent. Try again in a few minutes, or ask your admin to check "
               "Keeplane.")

# What the gateway's refusal says when Keeplane's check couldn't run, so the
# request never reached a model (D177): agentgateway's own text, then
# Keeplane's reasons when its storage or check is down.
CHECK_REFUSALS = ("external authorization failed",
                  "keeplane storage is unavailable",
                  "gateway authorization is unavailable")

# Spec 004 ST11 (ADR 030): the provider refused the developer's own key during
# a task, and the server's recheck confirmed it.
KEY_REFUSED = ("The provider refused your own key for {model}, so this task stopped. "
               "Replace it with `keeplane keys set --model {model}`. "
               "Run `keeplane keys list` to see your keys.")

NO_RUNTIME = ("Keeplane can't find OpenCode V2 " + opencode_adapter.VERSION + ". Install "
              "it, then put `opencode` on your PATH, pass --runtime PATH, or set "
              '"runtime" in your Keeplane settings file.')

WRONG_RUNTIME = ("Keeplane needs OpenCode V2 " + opencode_adapter.VERSION + ", and {path} "
                 "is another version or doesn't run. Install " + opencode_adapter.VERSION
                 + ", then put it on your PATH, pass --runtime PATH, or set \"runtime\" in your "
                 "Keeplane settings file.")

NOT_ALLOWED = "This model is not currently allowed for the project."

TASK_MODEL_FIELDS = {"project_id", "requested_model_id", "persona", "level",
                     "model_id", "chosen_by", "reason"}
CHOSEN_BY = {None, "developer", "persona_rule", "complexity_level", "first_allowed"}
KEY_REASONS = {"missing", "refused", "outdated"}


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


def task_model(issuer, project_id, credential, switch=None, *, persona=None, level=None):
    """Ask the server which allowed model a task with no --model goes to.

    The developer's saved switch is sent as ``model_id``: the server puts it
    before persona rules and levels, refuses it with 403 when the project
    doesn't allow it, and moves the task in its routing order only when the
    developer's own key for it can't be used (``reason``). The CLI names no
    persona or level yet; judging a task's level is task 004-03.
    """
    query = {name: value for name, value in
             (("model_id", switch), ("persona", persona), ("level", level))
             if value is not None} or None
    body = request(issuer, "/api/runtime/projects/" + project_id + "/task-model",
                   credential, query=query)
    try:
        data = json.loads(body)
        if (not isinstance(data, dict) or set(data) != TASK_MODEL_FIELDS
                or data["project_id"] != project_id
                or data["requested_model_id"] != switch
                or data["persona"] != persona or data["level"] != level
                or data["chosen_by"] not in CHOSEN_BY
                or (data["model_id"] is None) != (data["chosen_by"] is None)
                or (data["model_id"] is not None and (
                    not isinstance(data["model_id"], str)
                    or not 0 < len(data["model_id"]) <= 256
                    or any(ord(c) < 32 or ord(c) == 127 for c in data["model_id"])))):
            raise ValueError
        reason = data["reason"]
        if switch is None:
            valid = reason is None and data["chosen_by"] != "developer"
        elif reason is None:
            valid = data["model_id"] == switch and data["chosen_by"] == "developer"
        elif reason == "unavailable":
            valid = data["model_id"] is None
        else:
            valid = (reason in KEY_REASONS and data["model_id"] != switch
                     and data["chosen_by"] != "developer")
        if not valid:
            raise ValueError
    except (ValueError, UnicodeError, RecursionError, TypeError):
        raise ConnectionError("The server returned an invalid model choice.") from None
    return data


def chosen_model(issuer, project_id, model, credential, notify, *, switched=False):
    """Use another allowed model when the requested one needs the developer's key."""
    try:
        choice = model_choice(issuer, project_id, model, credential)
    except ConnectionError as error:
        if error.status == 404:
            return model  # An older server has no choice route; the gateway still checks.
        raise
    return moved_for_key(model, choice["reason"], choice["model_id"], notify,
                         switched=switched)


def moved_for_key(model, reason, other, notify, *, switched=False):
    """The model to use after the server's answer for a requested model.

    For the developer's saved switch the task moves and the switch stays; the
    notice says why (associate product owner, task 009-07).
    """
    if reason is None:
        return model
    if reason == "unavailable":
        raise ConnectionError(UNAVAILABLE.format(requested=model), 503)
    why = REASONS[reason].format(requested=model)
    fix = "keeplane keys set --model " + model
    action = "Add one" if reason == "missing" else "Replace it"
    if other is None:
        raise ConnectionError(
            "Add or replace your provider key: " + why
            + ", and no other allowed model is available for this project. Run `"
            + fix + "`.", 403)
    if switched:
        notify(OWN_KEY_MOVED.format(model=model, state=OWN_KEY[reason],
                                    task="this task", other=other))
    else:
        notify(why + "; using " + other + " instead. " + action + " with `" + fix + "`.")
    return other


def saved_switch(project_id):
    """The developer's `keeplane use` switch for this project, or None.

    A settings file the CLI can't trust stops a turn: it also names the
    runtime the CLI runs.
    """
    try:
        return settings_file.project_model(project_id)
    except settings_file.SettingsError as error:
        raise ConnectionError(str(error)) from None


class SwitchNotAllowed(ConnectionError):
    """The server refused the saved switch: the project doesn't allow it any more."""


def _route(issuer, project_id, credential, switch):
    """The task-model answer, or None from an older server without the route.

    A 403 for the switch itself means the project doesn't allow it any more;
    any other refusal keeps the server's own reason.
    """
    try:
        return task_model(issuer, project_id, credential, switch)
    except SignInExpired:
        raise
    except ConnectionError as error:
        if error.status == 404:
            return None
        if error.status == 403 and switch is not None and error.detail == MODEL_REFUSED:
            raise SwitchNotAllowed(
                SWITCH_NOT_ALLOWED.format(model=switch, sent=NOTHING_SENT), 403) from None
        if error.status == 403 and error.detail:
            # Its own sentence with one full stop, then what happened (associate
            # product owner); only `code` prints it, so nothing was sent.
            raise ConnectionError(
                error.detail.rstrip(". ") + ". " + PROJECT_REFUSED, 403) from None
        raise


def routed_model(issuer, project_id, credential, allowed, notify):
    """The model for a turn with no --model: the switch, else Keeplane's pick."""
    switch = saved_switch(project_id)
    if switch is not None and switch not in allowed:
        raise ConnectionError(
            SWITCH_NOT_ALLOWED.format(model=switch, sent=NOTHING_SENT), 403)
    routed = _route(issuer, project_id, credential, switch)
    if switch is None:
        if routed is None:  # An older server: no task-model route.
            raise ConnectionError(NO_ROUTED_MODEL, 404)
        if routed["model_id"] is None:
            raise ConnectionError(NO_ROUTED_MODEL)
        if routed["model_id"] not in allowed:
            raise ConnectionError(NOT_ALLOWED)
        notify(USING_PICK.format(model=routed["model_id"]))
        return routed["model_id"]
    if routed is None:
        # An older server: the switch goes through the model-choice route.
        model = chosen_model(issuer, project_id, switch, credential, notify,
                             switched=True)
    else:
        model = moved_for_key(switch, routed["reason"], routed["model_id"], notify,
                              switched=True)
    if model == switch:
        notify(USING_SWITCH.format(model=switch))
    return model


def current_choice(issuer, project_id, credential, allowed):
    """What the next task uses, for `keeplane models`.

    Returns (model or None, "you", "keeplane" or None, notices). Only the mark
    is lost when the choice can't be worked out; the list still shows.
    """
    try:
        switch = settings_file.project_model(project_id)
    except settings_file.SettingsError as error:
        return None, None, [str(error) + " " + UNMARKED]
    if switch is not None and switch not in allowed:
        return None, None, [SWITCH_NOT_ALLOWED.format(model=switch, sent="")]
    try:
        routed = _route(issuer, project_id, credential, switch)
    except SwitchNotAllowed:
        return None, None, [SWITCH_NOT_ALLOWED.format(model=switch, sent="")]
    except SignInExpired:
        raise
    except ConnectionError:
        routed = False  # The server can't say now; only the mark may be missing.
    if switch is None:
        model = routed["model_id"] if routed else None
        return (model, "keeplane", []) if model in allowed else (None, None, [])
    if not routed or routed["reason"] is None:
        return switch, "you", []  # An older or unavailable server: the switch stands.
    if routed["reason"] == "unavailable":
        return None, None, [SWITCH_UNAVAILABLE.format(model=switch)]
    other = routed["model_id"]
    if other is None or other not in allowed:
        return None, None, [OWN_KEY_NO_OTHER.format(
            model=switch, state=OWN_KEY[routed["reason"]])]
    return other, "keeplane", [OWN_KEY_MOVED.format(
        model=switch, state=OWN_KEY[routed["reason"]], task="your next task",
        other=other)]


def answered_by(stdout, model, allowed):
    """Every allowed model the runtime's events name, in order; else the one sent."""
    names = []
    for event in _events(stdout):
        for key, value in _walk(event):
            if key in ("modelID", "model_id", "model") and isinstance(value, str):
                value = value.removeprefix(opencode_adapter.PROVIDER + "/")
                if value in allowed and value not in names:
                    names.append(value)
    names = names or [model]
    return ANSWERED_BY.format(models=usage.joined(names))


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


def provider_refusal(stdout):
    """Whether one of the runtime's error events carries a 401 or 403.

    The gateway passes the provider's answer on, so a refused own key shows
    here like the gateway's own refusals; only the server's recheck tells
    them apart.
    """
    return any(
        key in ("statusCode", "status") and type(value) is int and value in (401, 403)
        for event in _events(stdout) if event.get("type") == "error"
        for key, value in _walk(event))


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


def error_statuses(stdout):
    """Every HTTP status in the runtime's error events."""
    return {
        value
        for event in _events(stdout) if event.get("type") == "error"
        for key, value in _walk(event)
        if key in ("statusCode", "status") and type(value) is int
    }


def check_refused(stdout):
    """Whether an error event is the gateway's refusal before any model was tried.

    The gateway answers so when Keeplane's route check can't run: its own
    "external authorization failed" when the app doesn't answer, or Keeplane's
    reason, passed on, when its storage is down.
    """
    text = " ".join(
        value.lower()
        for event in _events(stdout) if event.get("type") == "error"
        for _, value in _walk(event) if isinstance(value, str))
    return any(sign in text for sign in CHECK_REFUSALS)


def outage(result, issuer, credential):
    """GATEWAY_DOWN or SERVER_DOWN when an outage stopped a failed turn, else None.

    The relay says when the gateway didn't answer. Otherwise it is an outage
    only when the request never reached a model (D177): the gateway refused it
    because Keeplane's check couldn't run, and Keeplane itself doesn't answer,
    or answers with a 5xx, straight afterwards. A model that was tried and
    failed keeps its ST16 message, even while Keeplane is down.
    """
    more = "more " if any(
        isinstance(row, dict) and row.get("requests")
        for row in (getattr(result, "usage", None) or {}).values()) else ""
    if getattr(result, "gateway_unreachable", 0):
        return GATEWAY_DOWN.format(more=more)
    if not (any(status == 403 or 500 <= status <= 599
                for status in error_statuses(result.stdout))
            and check_refused(result.stdout)):
        return None
    try:
        account(issuer, credential)
    except Unreachable:
        return SERVER_DOWN.format(more=more)
    except ConnectionError as error:
        if error.status is not None and 500 <= error.status <= 599:
            return SERVER_DOWN.format(more=more)
    return None


def problem_message(problem, model, alternatives):
    """Tell the developer what happened and which allowed models they may choose."""
    message = STOPPED[problem].format(model=model)
    if alternatives is None:
        return message + SWITCH[problem] + "; `keeplane models` lists them."
    if not alternatives:
        return NO_OTHER_MODEL[problem].format(model=model)
    return message + SWITCH[problem] + ": " + ", ".join(alternatives) + "."


def run(profile_path, project_id, name, model, binary, directory, gateway, prompt,
        timeout=300, *, cancelled=None, instructions=(), state_dir=None, session=None,
        notify=None):
    """One coding turn. Only the profile and prompt are needed (Spec 009 ST30).

    The project comes from the repo, the gateway from the profile, the model
    from the developer's `keeplane use` switch or the server's task-model
    route, and the runtime from the settings file or PATH; each given value
    overrides.
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
        # 009-15: the checks before the runtime starts. Keeplane not answering,
        # or answering that it is unavailable, means nothing was sent.
        try:
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
                # The developer's `keeplane use` switch, else Keeplane's pick (ST17).
                model = routed_model(credential.issuer, project_id,
                                     credential.access_token, allowed, report)
                if model not in allowed:
                    raise ConnectionError(NOT_ALLOWED)
            else:
                if model not in allowed:
                    raise ConnectionError(NOT_ALLOWED)
                model = chosen_model(credential.issuer, project_id, model,
                                     credential.access_token, report)
                if model not in allowed:
                    raise ConnectionError(NOT_ALLOWED)
        except SignInExpired:
            raise
        except (Unreachable, KeeplaneUnavailable):
            # Keeplane's own answer; a model the server says can't be used
            # right now keeps its own message.
            raise ConnectionError(START_UNAVAILABLE) from None
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
        # ST11: a 401 or 403 on the developer's own key has the server recheck it
        # first. The server only answers a sign-in that still works, so a 401
        # it confirms as a refused key isn't an expired sign-in.
        key_refused = bool(result.returncode) and provider_refusal(result.stdout) and \
            provider_keys.refused_after_failure(credential.issuer, credential.access_token,
                                                project_id, model)
        refused = (gateway_refused_sign_in(result.stdout)
                   if result.returncode and not key_refused else None)
        if refused is not None:
            # ST29: the gateway refused the sign-in; nothing more is sent, not even
            # a request for other models.
            for secret in secrets:
                result.stdout = result.stdout.replace(secret, "[redacted]")
                result.stderr = result.stderr.replace(secret, "[redacted]")
            raise SignInExpired(more=refused, result=result)
        stopped = (outage(result, credential.issuer, credential.access_token)
                   if result.returncode and not key_refused else None)
        problem = (model_problem(result.stdout)
                   if result.returncode and not key_refused and not stopped else None)
        if key_refused:
            result.stderr += KEY_REFUSED.format(model=model) + "\n"
        elif stopped:
            result.stderr += stopped + "\n"
        elif problem:
            try:
                alternatives = model_alternatives(
                    credential.issuer, project_id, model, credential.access_token)
            except ConnectionError:
                alternatives = None  # An older server: the developer still gets the reason.
            result.stderr += problem_message(problem, model, alternatives) + "\n"
        elif not result.returncode:
            result.stderr += answered_by(result.stdout, model, allowed) + "\n"
        # ADR 029: one usage report per model, from the gateway's answers.
        result.stderr += usage.report_turn(credential.issuer, project_id,
                                           credential.access_token,
                                           getattr(result, "usage", None))
        for secret in secrets:
            result.stdout = result.stdout.replace(secret, "[redacted]")
            result.stderr = result.stderr.replace(secret, "[redacted]")
        return result
