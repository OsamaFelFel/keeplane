"""See which model answered, and switch with `keeplane use` (Spec 004 ST17).

Cases: tests/unit/cli-model-switch-cases.md (SW-01 to SW-13). Journey: DEV-02,
DEV-03. The signed-in server and runtime doubles come from the profile tests.
"""

import json
import os
import stat
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest

from components.cli import coding, keeplane, settings_file
from components.cli.server_connection import ConnectionError
from components.cli.sign_in_again import EXPIRED_NOT_SAVED
from tests.unit import test_cli_project_profile as profile_tests
from tests.unit import test_cli_repo_defaults as repo_defaults

PROJECT = repo_defaults.PROJECT
connected = profile_tests.connected
sample = repo_defaults.sample
saved_gateway = repo_defaults.saved_gateway
fake_runtime = profile_tests.runtime
native_model = profile_tests.native_model


def run(monkeypatch, *arguments):
    monkeypatch.setattr("sys.argv", ["keeplane", *arguments])
    return keeplane.main()


def routes(server):
    return [(row[0], row[1]) for row in server.calls]


def task_model_queries(server):
    return [
        parse_qs(urlsplit(path).query)
        for _, path in routes(server)
        if "/task-model" in path
    ]


@pytest.fixture
def allowed(sample):
    sample.server.model_ids = ["coder", "general"]
    return sample


def test_sw_01_use_saves_an_allowed_model_for_this_repo(allowed, monkeypatch, capsys):
    assert run(monkeypatch, "use", "general") == 0
    assert capsys.readouterr().out == (
        "This repo's next tasks use general. "
        "Run `keeplane use --auto` to let Keeplane choose again.\n"
    )
    assert settings_file.project_model(PROJECT) == "general"
    assert stat.S_IMODE(os.stat(settings_file.path()).st_mode) == 0o600
    # Only the account and the allowed list are asked; nothing is sent to a model.
    assert routes(allowed.server) == [
        ("GET", "/api/runtime/session"),
        ("GET", f"/api/runtime/projects/{PROJECT}/models"),
    ]
    # The switch belongs to this project only.
    assert settings_file.project_model(str(uuid.uuid4())) is None


def test_sw_02_a_model_the_project_doesnt_allow_is_refused_and_nothing_saved(
    allowed, monkeypatch, capsys
):
    assert run(monkeypatch, "use", "outside") == 1
    assert capsys.readouterr().err.strip() == (
        "outside isn't allowed for this project. Nothing was saved. "
        "Choose one that `keeplane models` lists."
    )
    assert settings_file.project_model(PROJECT) is None
    assert not settings_file.path().exists()


def test_sw_03_code_sends_the_switch_and_says_which_model_answered(
    allowed,
    fake_runtime,
    saved_gateway,
    monkeypatch,
    capsys,
):
    settings_file.set_project_model(PROJECT, "general")
    assert run(monkeypatch, "code", "Make the failing test pass") == 0
    output = capsys.readouterr()
    assert output.out == "Coding finished.\n"
    assert output.err == (
        "Using general for this task, as you chose with `keeplane use`. "
        "Run `keeplane use --auto` to let Keeplane choose.\n"
        "Answered by general.\n"
    )
    # The server puts the developer's switch before persona rules and levels.
    assert task_model_queries(allowed.server) == [{"model_id": ["general"]}]
    assert not any("/model-choice" in path for _, path in routes(allowed.server))
    assert native_model(fake_runtime) == "keeplane/general"


def test_sw_04_use_auto_clears_the_switch_without_signing_in(
    allowed,
    fake_runtime,
    saved_gateway,
    monkeypatch,
    capsys,
):
    settings_file.set_project_model(PROJECT, "general")
    credential = os.path.join(allowed.profile, "credential.json")
    held = credential + ".held"
    os.rename(credential, held)
    assert run(monkeypatch, "use", "--auto") == 0
    assert capsys.readouterr().out == (
        "This repo's next tasks use the model Keeplane chooses.\n"
    )
    assert settings_file.project_model(PROJECT) is None
    assert allowed.server.calls == []
    # Clearing twice is fine.
    assert run(monkeypatch, "use", "--auto") == 0
    capsys.readouterr()
    os.rename(held, credential)
    assert run(monkeypatch, "code", "Fix it") == 0
    assert capsys.readouterr().err == (
        "Using coder for this task, chosen by Keeplane. "
        "Run `keeplane use <model>` to choose another.\n"
        "Answered by coder.\n"
    )
    assert task_model_queries(allowed.server) == [{}]


def test_sw_05_models_marks_the_current_choice(allowed, monkeypatch, capsys):
    assert run(monkeypatch, "models") == 0
    listing = json.loads(capsys.readouterr().out)
    assert listing == {
        "project_id": PROJECT,
        "models": [
            {"id": "coder", "current": True},
            {"id": "general", "current": False},
        ],
        "chosen_by": "keeplane",
    }
    settings_file.set_project_model(PROJECT, "general")
    assert run(monkeypatch, "models") == 0
    listing = json.loads(capsys.readouterr().out)
    assert [row["current"] for row in listing["models"]] == [False, True]
    assert listing["chosen_by"] == "you"
    # With a switch, the route is asked about the switch itself, so the mark
    # shows what the next task really uses.
    assert task_model_queries(allowed.server) == [{}, {"model_id": ["general"]}]


def test_sw_05_a_switch_the_project_no_longer_allows_is_named(
    allowed, monkeypatch, capsys
):
    settings_file.set_project_model(PROJECT, "retired")
    assert run(monkeypatch, "models") == 0
    output = capsys.readouterr()
    listing = json.loads(output.out)
    assert not any(row["current"] for row in listing["models"])
    assert listing["chosen_by"] is None
    assert output.err.strip() == (
        "You switched this repo to retired, but it isn't allowed for this project "
        "any more. Run `keeplane use <model>` with a model `keeplane models` lists, "
        "or `keeplane use --auto` to let Keeplane choose."
    )
    # The server's own refusal of the switch reads the same.
    settings_file.set_project_model(PROJECT, "general")
    allowed.server.task_model_status = 403
    allowed.server.task_model_reply = {"error": coding.MODEL_REFUSED}
    assert run(monkeypatch, "models") == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["chosen_by"] is None
    assert output.err.strip() == coding.SWITCH_NOT_ALLOWED.format(
        model="general", sent=""
    )


@pytest.mark.parametrize(
    "reason, state", [("missing", "is missing"), ("refused", "is refused")]
)
def test_sw_05_the_mark_follows_the_task_when_the_own_key_cant_be_used(
    allowed, monkeypatch, capsys, reason, state
):
    settings_file.set_project_model(PROJECT, "general")
    allowed.server.task_model_reply = {
        "model_id": "coder",
        "chosen_by": "first_allowed",
        "reason": reason,
    }
    assert run(monkeypatch, "models") == 0
    output = capsys.readouterr()
    listing = json.loads(output.out)
    assert [row["current"] for row in listing["models"]] == [True, False]
    assert listing["chosen_by"] == "keeplane"
    assert output.err.strip() == (
        f"Your own key for general {state}, so your next task uses coder. "
        "Run `keeplane keys list` to see your keys."
    )
    assert task_model_queries(allowed.server) == [{"model_id": ["general"]}]


@pytest.mark.parametrize(
    "reply, notice",
    [
        (
            {"model_id": None, "chosen_by": None, "reason": "unavailable"},
            "general is approved for this project but can't be used right now.",
        ),
        (
            {"model_id": None, "chosen_by": None, "reason": "missing"},
            (
                "Your own key for general is missing, and no other allowed model is "
                "available for this project. Run `keeplane keys list` to see your keys."
            ),
        ),
    ],
    ids=["unavailable", "no-other-model"],
)
def test_sw_05_a_switch_no_task_can_use_marks_nothing_and_says_why(
    allowed, monkeypatch, capsys, reply, notice
):
    settings_file.set_project_model(PROJECT, "general")
    allowed.server.task_model_reply = reply
    assert run(monkeypatch, "models") == 0
    output = capsys.readouterr()
    listing = json.loads(output.out)
    assert not any(row["current"] for row in listing["models"])
    assert listing["chosen_by"] is None
    assert output.err.strip() == notice


def test_sw_05_a_broken_settings_file_loses_only_the_mark(
    allowed, fake_runtime, saved_gateway, monkeypatch, capsys
):
    settings_file.set_project_model(PROJECT, "general")
    settings_file.path().write_text("{not json")
    assert run(monkeypatch, "models") == 0
    output = capsys.readouterr()
    listing = json.loads(output.out)
    assert [row["id"] for row in listing["models"]] == ["coder", "general"]
    assert listing["chosen_by"] is None
    assert output.err.strip() == (
        f"Keeplane's settings file {settings_file.path()} isn't valid JSON. "
        "Your `keeplane use` choice isn't marked until the file is fixed."
    )
    # A turn still stops: the same file names the runtime the CLI runs.
    assert run(monkeypatch, "code", "Fix it") == 1
    assert "isn't valid JSON" in capsys.readouterr().err
    assert fake_runtime[1] == []


@pytest.mark.parametrize("status", [404, 503])
def test_sw_05_the_list_still_shows_when_the_pick_cant_be_asked(
    allowed, monkeypatch, capsys, status
):
    allowed.server.task_model_status = status
    assert run(monkeypatch, "models") == 0
    listing = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in listing["models"]] == ["coder", "general"]
    assert listing["chosen_by"] is None
    assert not any(row["current"] for row in listing["models"])


def test_sw_06_code_with_a_switch_the_project_doesnt_allow_sends_nothing(
    allowed,
    fake_runtime,
    saved_gateway,
    monkeypatch,
    capsys,
):
    settings_file.set_project_model(PROJECT, "retired")
    assert run(monkeypatch, "code", "Fix it") == 1
    assert capsys.readouterr().err.strip() == (
        "You switched this repo to retired, but it isn't allowed for this project "
        "any more, so nothing was sent. Run `keeplane use <model>` with a model "
        "`keeplane models` lists, or `keeplane use --auto` to let Keeplane choose."
    )
    assert fake_runtime[1] == [] and task_model_queries(allowed.server) == []
    # The server's own refusal of the model (keeplane #178) reads the same.
    settings_file.set_project_model(PROJECT, "general")
    allowed.server.task_model_status = 403
    allowed.server.task_model_reply = {"error": coding.MODEL_REFUSED}
    assert run(monkeypatch, "code", "Fix it") == 1
    assert capsys.readouterr().err.strip() == coding.SWITCH_NOT_ALLOWED.format(
        model="general", sent=coding.NOTHING_SENT
    )
    assert fake_runtime[1] == []


def test_sw_06_another_refusal_keeps_the_servers_own_reason(
    allowed, fake_runtime, saved_gateway, monkeypatch, capsys
):
    settings_file.set_project_model(PROJECT, "general")
    allowed.server.task_model_status = 403
    allowed.server.task_model_reply = {"error": "This project is unavailable"}
    assert run(monkeypatch, "code", "Fix it") == 1
    assert capsys.readouterr().err.strip() == "This project is unavailable."
    assert fake_runtime[1] == []
    # A reason that isn't short plain text isn't shown.
    allowed.server.task_model_reply = {"error": "Bad\x1b[31m"}
    assert run(monkeypatch, "code", "Fix it") == 1
    assert capsys.readouterr().err.strip() == "The requested action is unavailable."


@pytest.mark.parametrize(
    "reason, text",
    [
        ("missing", "Your own key for general is missing, so this task uses coder."),
        ("refused", "Your own key for general is refused, so this task uses coder."),
    ],
)
def test_sw_07_without_a_usable_own_key_the_server_moves_the_task_and_says_so(
    allowed,
    fake_runtime,
    saved_gateway,
    monkeypatch,
    capsys,
    reason,
    text,
):
    settings_file.set_project_model(PROJECT, "general")
    allowed.server.task_model_reply = {
        "model_id": "coder",
        "chosen_by": "first_allowed",
        "reason": reason,
    }
    assert run(monkeypatch, "code", "Fix it") == 0
    error = capsys.readouterr().err
    assert error == (
        text + " Run `keeplane keys list` to see your keys.\nAnswered by coder.\n"
    )
    assert "as you chose" not in error
    assert native_model(fake_runtime) == "keeplane/coder"
    # The switch itself stays; the next task tries it again.
    assert settings_file.project_model(PROJECT) == "general"


def test_sw_07_no_other_model_for_the_key_sends_nothing(
    allowed,
    fake_runtime,
    saved_gateway,
    monkeypatch,
    capsys,
):
    settings_file.set_project_model(PROJECT, "general")
    allowed.server.task_model_reply = {
        "model_id": None,
        "chosen_by": None,
        "reason": "missing",
    }
    assert run(monkeypatch, "code", "Fix it") == 1
    assert "no other allowed model is available" in capsys.readouterr().err
    assert fake_runtime[1] == []


def test_sw_08_a_switch_that_cant_be_used_right_now_sends_nothing(
    allowed,
    fake_runtime,
    saved_gateway,
    monkeypatch,
    capsys,
):
    settings_file.set_project_model(PROJECT, "general")
    allowed.server.task_model_reply = {
        "model_id": None,
        "chosen_by": None,
        "reason": "unavailable",
    }
    assert run(monkeypatch, "code", "Fix it") == 1
    assert capsys.readouterr().err.strip() == coding.UNAVAILABLE.format(
        requested="general"
    )
    assert fake_runtime[1] == []


def test_sw_09_an_older_server_gets_the_switch_through_the_model_choice_route(
    allowed,
    fake_runtime,
    saved_gateway,
    monkeypatch,
    capsys,
):
    settings_file.set_project_model(PROJECT, "general")
    allowed.server.task_model_status = 404
    assert run(monkeypatch, "code", "Fix it") == 0
    assert (
        "GET",
        f"/api/runtime/projects/{PROJECT}/model-choice?model_id=general",
    ) in routes(allowed.server)
    assert native_model(fake_runtime) == "keeplane/general"
    assert capsys.readouterr().err.endswith("Answered by general.\n")


def test_sw_10_model_flag_is_for_one_turn_and_keeps_the_switch(
    allowed,
    fake_runtime,
    saved_gateway,
    monkeypatch,
    capsys,
):
    settings_file.set_project_model(PROJECT, "general")
    assert run(monkeypatch, "code", "--model", "coder", "Fix it") == 0
    assert native_model(fake_runtime) == "keeplane/coder"
    assert capsys.readouterr().err == "Answered by coder.\n"
    assert task_model_queries(allowed.server) == []
    assert settings_file.project_model(PROJECT) == "general"


@pytest.mark.parametrize(
    "switch, reply",
    [
        (None, {"requested_model_id": "general"}),
        ("general", {"requested_model_id": None}),
        (None, {"chosen_by": "developer"}),
        ("general", {"model_id": "coder"}),
        ("general", {"model_id": "general", "reason": "missing"}),
        ("general", {"model_id": "coder", "reason": "unavailable"}),
        (None, {"reason": "missing"}),
        (None, {"persona": "architect"}),
        (None, {"chosen_by": "guess"}),
        (None, {"model_id": None}),
    ],
    ids=[
        "switch-not-asked",
        "switch-dropped",
        "developer-without-switch",
        "switch-replaced",
        "same-model-moved",
        "unavailable-with-model",
        "reason-without-switch",
        "persona-not-asked",
        "unknown-step",
        "no-model-but-step",
    ],
)
def test_sw_11_answers_that_dont_match_the_question_are_refused(
    monkeypatch, switch, reply
):
    project = str(uuid.uuid4())
    answer = {
        "project_id": project,
        "requested_model_id": switch,
        "persona": None,
        "level": None,
        "model_id": switch or "coder",
        "chosen_by": "developer" if switch else "first_allowed",
        "reason": None,
        **reply,
    }
    monkeypatch.setattr(
        coding, "request", lambda *args, **kwargs: json.dumps(answer).encode()
    )
    with pytest.raises(ConnectionError, match="invalid model choice"):
        coding.task_model("https://keeplane.test", project, "token", switch)


def test_sw_12_only_a_finished_turn_says_which_model_answered():
    assert coding.answered_by("", "coder", {"coder"}) == "Answered by coder."
    events = "\n".join(
        json.dumps(event)
        for event in (
            {"type": "step_start", "part": {"modelID": "keeplane/coder"}},
            {"type": "text", "part": {"model": "general"}},
            {"type": "step_start", "part": {"modelID": "coder"}},
            {"type": "text", "part": {"model": "not-allowed"}},
        )
    )
    assert (
        coding.answered_by(events, "coder", {"coder", "general"})
        == "Answered by coder and general."
    )
    assert (
        coding.answered_by(events, "coder", {"coder", "general", "not-allowed"})
        == "Answered by coder, general and not-allowed."
    )
    # The decided ST16 sentences (issues #52 and #57) are unchanged.
    assert coding.NO_OTHER_MODEL["down"].format(model="coder") == (
        "coder is unavailable right now and no other model is allowed for this "
        "project. Wait and try again, or ask your admin to set up another model."
    )
    assert coding.NO_OTHER_MODEL["too_big"].format(model="coder") == (
        "This task is too big for coder's context and no other model is allowed for "
        "this project. Make the task smaller, or ask your admin to set up a model "
        "with a larger context."
    )
    assert "--model" not in coding.problem_message("down", "coder", ["general"])
    assert "--model" not in coding.problem_message("too_big", "coder", None)
    assert "--model" not in coding.NO_ROUTED_MODEL + coding.USING_PICK


def test_sw_13_use_needs_one_model_or_auto_and_a_sign_in(allowed, monkeypatch, capsys):
    for arguments in (["use"], ["use", "general", "--auto"]):
        with pytest.raises(SystemExit) as stopped:
            run(monkeypatch, *arguments)
        assert stopped.value.code == 2
        assert "Name one MODEL, or pass --auto." in capsys.readouterr().err
    credential = os.path.join(allowed.profile, "credential.json")
    os.rename(credential, credential + ".held")
    assert run(monkeypatch, "use", "general") == 1
    assert capsys.readouterr().err.strip() == keeplane.SIGNED_OUT_USE
    os.rename(credential + ".held", credential)
    allowed.server.status = 401
    assert run(monkeypatch, "use", "general") == 1
    assert capsys.readouterr().err.strip() == EXPIRED_NOT_SAVED
    assert settings_file.project_model(PROJECT) is None
