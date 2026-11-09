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

import json
import math

if __package__:
    from . import settings_file
else:
    import settings_file

# The reviewed settings, by the name the gateway receives them under.
ALLOWED = ("temperature", "top_p", "max_tokens", "reasoning_effort")
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")
MAX_TOKENS = 1_000_000


class RequestSettingsError(settings_file.SettingsError):
    pass


def _shown(text, limit=64):
    """Text as printed in a message: plain if short and printable, else quoted."""
    if (
        isinstance(text, str)
        and 0 < len(text) <= limit
        and text.isprintable()
        and text.strip() == text
    ):
        return text
    shown = json.dumps(text, ensure_ascii=True)
    return shown if len(shown) <= limit else shown[: limit - 4] + '..."'


def _value(value, limit=64):
    """An allowed setting's value as JSON, shortened if long."""
    text = json.dumps(value, ensure_ascii=True)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


# Each setting's range, as the message gives it: (low, high, whole numbers only).
RANGES = {
    "temperature": (0, 2, False),
    "top_p": (0, 1, False),
    "max_tokens": (1, MAX_TOKENS, True),
}


def _valid(name, value):
    if name == "reasoning_effort":
        return value in REASONING_EFFORTS
    low, high, whole = RANGES[name]
    if whole and not (isinstance(value, int) and not isinstance(value, bool)):
        return False
    return _number(value) and low <= value <= high


def _allowed_values(name):
    if name == "reasoning_effort":
        return (
            "one of "
            + ", ".join(REASONING_EFFORTS[:-1])
            + " or "
            + REASONING_EFFORTS[-1]
        )
    low, high, whole = RANGES[name]
    span = "from " + format(low, ",") + " to " + format(high, ",")
    return ("a whole number " if whole else "") + span


def check(model_id, values):
    """Return a model's checked request settings, or refuse them.

    A refused setting's value is never printed unless the setting is one of
    the four allowed: a provider, address, key or plugin setting may hold a
    secret.
    """
    model = _shown(model_id, 256)
    if not isinstance(values, dict):
        raise RequestSettingsError(
            "Your Keeplane settings for " + model + " aren't a set of request "
            "settings, so nothing was sent. Use "
            + ", ".join(ALLOWED[:-1])
            + " or "
            + ALLOWED[-1]
            + "."
        )
    for name in values:
        if name not in ALLOWED:
            raise RequestSettingsError(
                "Your Keeplane settings for "
                + model
                + " have "
                + _shown(name)
                + ", which Keeplane doesn't pass on, so nothing was sent. Use "
                + ", ".join(ALLOWED[:-1])
                + " or "
                + ALLOWED[-1]
                + "."
            )
    for name in ALLOWED:
        if name in values and not _valid(name, values[name]):
            raise RequestSettingsError(
                "Your Keeplane settings for "
                + model
                + " set "
                + name
                + " to "
                + _value(values[name])
                + ", but it must be "
                + _allowed_values(name)
                + ", so nothing was sent."
            )
    return {name: values[name] for name in ALLOWED if name in values}


def for_model(model_id):
    """The checked request settings saved for a model, or an empty object."""
    return check(model_id, settings_file.request_settings(model_id))
