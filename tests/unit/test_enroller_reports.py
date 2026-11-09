"""What the model enroller's loop reports after each pass.

Cases ER-01 to ER-05 in enroller-reports-cases.md (issue #253). The loop is
driven with a fake enroller that returns set results, and stops on the sleep
after the last one; nothing is enrolled and no gateway or database is used.
"""

from io import StringIO

import pytest
from django.core.management import load_command_class
from django.core.management.base import OutputWrapper
from model_registry.management.commands import run_model_enroller as command
from model_registry.model_enroller import Enrolment

HELD = (
    "A model change is waiting for requests already under way to finish. "
    "Changed or removed models stay refused until then."
)
NONE = "No model is enrolled for protected access."


class Stop(Exception):
    pass


def reports(monkeypatch, settings, *results):
    """The lines the loop writes for these passes, in order."""
    passes = list(results)

    class FakeEnroller:
        def __init__(self, *args, **kwargs):
            pass

        def reconcile(self):
            return passes.pop(0)

    def sleep(_seconds):
        if not passes:
            raise Stop

    settings.RUNTIME_GUARD_MANIFEST_FILE = "/installed/manifest.json"
    settings.RUNTIME_AUTHORIZER_KEY_FILE = "/installed/callback-key"
    monkeypatch.setattr(command, "DjangoModelEnroller", FakeEnroller)
    monkeypatch.setattr(command, "DjangoRuntimeInstallation", lambda *a, **k: None)
    monkeypatch.setattr(command, "guard_status_recorder", lambda: (None, None))
    monkeypatch.setattr(command.time, "sleep", sleep)
    out = StringIO()
    runner = load_command_class("model_registry", "run_model_enroller")
    runner.stdout = OutputWrapper(out)
    with pytest.raises(Stop):
        runner.handle(
            once=False,
            interval=1.0,
            directory="/installed",
            trusted_file="/installed/trusted.json",
            callback_host="app:3000",
        )
    return out.getvalue().splitlines()


def test_er01_a_hold_that_ends_with_no_models_is_reported(monkeypatch, settings):
    # The issue: models left from before a full reset are removed after the hold.
    lines = reports(
        monkeypatch,
        settings,
        Enrolment("held", ()),
        Enrolment("held", ()),
        Enrolment("unchanged", ()),
        Enrolment("unchanged", ()),
    )
    assert lines == [HELD, NONE]


def test_er02_a_hold_that_ends_by_withdrawing_every_model_is_reported(
    monkeypatch, settings
):
    lines = reports(
        monkeypatch, settings, Enrolment("held", ()), Enrolment("withdrawn", ())
    )
    assert lines == [HELD, NONE]


def test_er03_a_hold_that_ends_with_models_reports_the_count(monkeypatch, settings):
    lines = reports(
        monkeypatch,
        settings,
        Enrolment("held", ()),
        Enrolment("enrolled", ("a", "b")),
        Enrolment("unchanged", ("a", "b")),
    )
    assert lines == [HELD, "Protected access is ready: 2 models are enrolled."]


def test_er04_a_hold_undone_before_it_ends_reports_the_models_kept(
    monkeypatch, settings
):
    # The change was reverted during the hold, so the guard already matches.
    lines = reports(
        monkeypatch,
        settings,
        Enrolment("enrolled", ("a",)),
        Enrolment("held", ()),
        Enrolment("unchanged", ("a",)),
        Enrolment("unchanged", ("a",)),
    )
    assert lines == [
        "Protected access is ready: 1 model is enrolled.",
        HELD,
        "Protected access is up to date: 1 model is enrolled.",
    ]


def test_er05_passes_with_nothing_new_stay_quiet(monkeypatch, settings):
    lines = reports(
        monkeypatch,
        settings,
        Enrolment("unchanged", ()),
        Enrolment("unchanged", ()),
        Enrolment("enrolled", ("a",)),
        Enrolment("unchanged", ("a",)),
        Enrolment("held", ()),
        Enrolment("held", ()),
    )
    assert lines == [NONE, "Protected access is ready: 1 model is enrolled.", HELD]


@pytest.mark.parametrize(
    ("last", "result", "reported"),
    [
        (None, Enrolment("held", ()), True),
        (Enrolment("held", ()), Enrolment("held", ()), False),
        (Enrolment("held", ()), Enrolment("unchanged", ()), True),
        (Enrolment("held", ()), Enrolment("unchanged", ("a",)), True),
        (Enrolment("unchanged", ()), Enrolment("unchanged", ()), False),
        (Enrolment("enrolled", ("a",)), Enrolment("unchanged", ("a",)), False),
        (Enrolment("enrolled", ("a",)), Enrolment("unchanged", ()), True),
    ],
)
def test_er06_which_passes_are_reported(last, result, reported):
    assert command.changed_report(last, result) is reported
