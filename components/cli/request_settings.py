"""Request settings a developer sets per model (Spec 004 ST26, ADR 030).

They live in the ``models`` section of the CLI settings file, keyed by the
gateway model ID::

    {"models": {"coder": {"temperature": 0.2, "top_p": 0.9,
                          "max_tokens": 4096, "reasoning_effort": "low"}}}

Only these four settings are allowed. They are given to the runtime as the
model's request body overlay, so each one reaches the gateway, and through it
the model, with the same name and value. Anything else in a model's settings,
such as a provider, an address, a key or a plugin, is refused: the runtime
only ever reaches the gateway (D185).
"""

import math

if __package__:
    from . import settings_file
else:
    import settings_file

# The reviewed settings, by the name the gateway receives them under.
ALLOWED = ("temperature", "top_p", "max_tokens", "reasoning_effort")
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")
MAX_TOKENS = 1_000_000
# Words that show a setting tries to choose where or how a request is sent.
ROUTING_WORDS = {
    "a provider": ("provider", "package", "npm", "canonical"),
    "an address": ("url", "uri", "address", "endpoint", "host", "proxy", "base"),
    "a key": (
        "key",
        "accesstoken",
        "refreshtoken",
        "bearer",
        "auth",
        "secret",
        "credential",
        "password",
        "header",
        "env",
    ),
    "a plugin": ("plugin", "mcp", "tool"),
}


class RequestSettingsError(settings_file.SettingsError):
    pass


def _refused(model_id, reason):
    return RequestSettingsError(
        "Keeplane's settings file "
        + str(settings_file.path())
        + ' has request settings for "'
        + model_id
        + '" that '
        + reason
    )


def _number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _valid(name, value):
    if name == "temperature":
        return _number(value) and 0 <= value <= 2
    if name == "top_p":
        return _number(value) and 0 <= value <= 1
    if name == "max_tokens":
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 < value <= MAX_TOKENS
        )
    return value in REASONING_EFFORTS


def _kind(name):
    folded = str(name).lower().replace("-", "").replace("_", "")
    for kind, words in ROUTING_WORDS.items():
        if any(word in folded for word in words):
            return kind
    return None


def check(model_id, values):
    """Return a model's checked request settings, or refuse them."""
    if not isinstance(values, dict):
        raise _refused(model_id, "aren't an object.")
    for name in values:
        if name in ALLOWED:
            continue
        kind = _kind(name)
        if kind is not None:
            raise _refused(
                model_id,
                'set "' + str(name) + '", ' + kind + " setting. Keeplane "
                "always sends requests to its gateway, so provider, address, key and "
                "plugin settings aren't allowed.",
            )
        raise _refused(
            model_id,
            'set "' + str(name) + "\", which Keeplane doesn't pass on. Use "
            "only " + ", ".join(ALLOWED[:-1]) + " or " + ALLOWED[-1] + ".",
        )
    for name in ALLOWED:
        if name in values and not _valid(name, values[name]):
            raise _refused(
                model_id, 'set "' + name + "\" to a value it can't have. " + HINTS[name]
            )
    return {name: values[name] for name in ALLOWED if name in values}


HINTS = {
    "temperature": "Use a number from 0 to 2.",
    "top_p": "Use a number from 0 to 1.",
    "max_tokens": "Use a whole number from 1 to " + format(MAX_TOKENS, ",") + ".",
    "reasoning_effort": "Use one of " + ", ".join(REASONING_EFFORTS) + ".",
}


def for_model(model_id):
    """The checked request settings saved for a model, or an empty object."""
    return check(model_id, settings_file.request_settings(model_id))
