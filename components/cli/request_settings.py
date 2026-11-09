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
import re

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


USE = "Use " + ", ".join(ALLOWED[:-1]) + " or " + ALLOWED[-1] + "."
PLAIN_NAME = re.compile(r"[A-Za-z0-9_]{1,32}")
PLAIN_WORD = re.compile(r"[A-Za-z]{1,16}")


def _name(name):
    """A setting's name in quotes, or None when it must not be printed."""
    if isinstance(name, str) and PLAIN_NAME.fullmatch(name):
        return '"' + name + '"'
    return None


def _value(name, value):
    """A refused value as printed, or None when it must not be printed.

    Only a finite number, or for reasoning_effort a plain word of up to 16
    letters (in quotes), is ever shown: anything else (text, an object, a
    list, true or false) might be a key or an address put in the wrong place.
    """
    if _number(value):
        return json.dumps(value)
    if (
        name == "reasoning_effort"
        and isinstance(value, str)
        and PLAIN_WORD.fullmatch(value)
    ):
        return '"' + value + '"'
    return None


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

    ``model_id`` is the task's model, never a key read from the file. A
    setting Keeplane doesn't pass on, such as a provider, address, key or
    plugin setting, is named only when its name is plain, and never with its
    value. An allowed setting's value is printed only when it is a finite
    number, or a plain word for reasoning_effort; anything else is described.
    """
    start = "Your Keeplane settings for " + model_id
    if not isinstance(values, dict):
        raise RequestSettingsError(
            start + " aren't a set of request settings, so nothing was sent. " + USE
        )
    for name in values:
        if name not in ALLOWED:
            shown = _name(name)
            if shown is None:
                raise RequestSettingsError(
                    start + " have a setting Keeplane doesn't pass on, so nothing "
                    "was sent. " + USE
                )
            raise RequestSettingsError(
                start + " have " + shown + ", which Keeplane doesn't pass on, so "
                "nothing was sent. " + USE
            )
    for name in ALLOWED:
        if name in values and not _valid(name, values[name]):
            shown = _value(name, values[name])
            start_value = start + " set " + name + " to "
            if shown is not None:
                raise RequestSettingsError(
                    start_value
                    + shown
                    + ", but it must be "
                    + _allowed_values(name)
                    + ", so nothing was sent."
                )
            if name == "reasoning_effort":
                raise RequestSettingsError(
                    start_value
                    + "something that isn't "
                    + _allowed_values(name)
                    + ", so nothing was sent."
                )
            raise RequestSettingsError(
                start_value + "something that isn't a number, so nothing was sent."
            )
    return {name: values[name] for name in ALLOWED if name in values}


def for_model(model_id):
    """The checked request settings saved for a model, or an empty object."""
    return check(model_id, settings_file.request_settings(model_id))
