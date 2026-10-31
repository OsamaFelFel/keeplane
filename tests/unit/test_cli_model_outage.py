"""Spec 004 ST16: after the gateway's retries, the CLI says what to do next."""

import json
import subprocess
import uuid

import pytest

from components.cli import coding, opencode_adapter
from tests.unit.test_cli_project_profile import (  # noqa: F401
    code,
    connected,
    native_model,
    runtime,
)


def failed_turn(monkeypatch, fake, event):
    def turn(command, **options):
        fake[1].append((command, options))
        return subprocess.CompletedProcess(command, 0, json.dumps(event) + "\n", "")

    monkeypatch.setattr(opencode_adapter, "coding_turn", turn)


def api_error(status, message="Service Unavailable"):
    return {
        "type": "error",
        "error": {
            "name": "APIError",
            "data": {"message": message, "statusCode": status, "isRetryable": True},
        },
    }


TOO_BIG = api_error(
    400, "This model's maximum context length is 8 tokens. (context_length_exceeded)"
)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_a_model_still_down_after_the_retries_names_the_alternatives(
    connected, runtime, monkeypatch, tmp_path, capsys, status  # noqa: F811
):
    connected.model_ids = ["coder", "general", "local"]
    connected.alternatives = ["general", "local"]
    failed_turn(monkeypatch, runtime, api_error(status))
    project = str(uuid.uuid4())
    assert code(monkeypatch, connected, runtime, project, tmp_path) == 1
    # Exactly one turn with the requested model: the CLI never switches.
    assert len(runtime[1]) == 1 and native_model(runtime) == "keeplane/coder"
    output = capsys.readouterr()
    assert output.err.endswith(
        "coder is unavailable right now, so this task stopped. Wait and try again, "
        "or run it with another model allowed for this project using --model: "
        "general, local.\n"
    )
    assert json.loads(output.out)["type"] == "error"  # The native error still shows.
    assert (
        "GET",
        f"/api/runtime/projects/{project}/model-alternatives?model_id=coder",
    ) in [(row[0], row[1]) for row in connected.calls]
    assert connected.access not in output.out + output.err


def test_no_alternative_uses_the_existing_no_model_message(
    connected, runtime, monkeypatch, tmp_path, capsys  # noqa: F811
):
    failed_turn(monkeypatch, runtime, api_error(503))
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert capsys.readouterr().err == (
        "coder is unavailable right now, so this task stopped. Wait and try again. "
        + coding.NO_MODELS
        + "\n"
    )


def test_a_task_too_big_for_the_model_names_the_problem_and_alternatives(
    connected, runtime, monkeypatch, tmp_path, capsys  # noqa: F811
):
    connected.model_ids = ["coder", "large"]
    connected.alternatives = ["large"]
    failed_turn(monkeypatch, runtime, TOO_BIG)
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert len(runtime[1]) == 1 and native_model(runtime) == "keeplane/coder"
    assert capsys.readouterr().err.endswith(
        "This task is too big for coder's context, so it stopped. Run it with another "
        "model allowed for this project using --model: large.\n"
    )


def test_too_big_without_an_alternative_uses_the_no_model_message(
    connected, runtime, monkeypatch, tmp_path, capsys  # noqa: F811
):
    failed_turn(monkeypatch, runtime, TOO_BIG)
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert capsys.readouterr().err.endswith(
        "This task is too big for coder's context, so it stopped. " + coding.NO_MODELS + "\n"
    )


@pytest.mark.parametrize("status", [404, 503])
def test_an_older_or_unavailable_server_still_gets_the_reason(
    connected, runtime, monkeypatch, tmp_path, capsys, status  # noqa: F811
):
    connected.alternatives_status = status
    failed_turn(monkeypatch, runtime, api_error(503))
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert capsys.readouterr().err.endswith(
        "coder is unavailable right now, so this task stopped. Wait and try again, or "
        "run it with another model allowed for this project using --model; "
        "`keeplane models` lists them.\n"
    )


@pytest.mark.parametrize(
    "alternatives",
    [["coder"], ["a b"], ["x"] * 2, "general", [7]],
    ids=["itself", "space", "duplicate", "not-a-list", "not-text"],
)
def test_malformed_alternatives_are_not_shown(
    connected, runtime, monkeypatch, tmp_path, capsys, alternatives  # noqa: F811
):
    connected.alternatives = alternatives
    failed_turn(monkeypatch, runtime, api_error(503))
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 1
    assert "`keeplane models` lists them." in capsys.readouterr().err


@pytest.mark.parametrize(
    "event",
    [
        api_error(401, "Unauthorized"),
        api_error(403, "This model is not eligible for the project"),
        api_error(400, "Bad request"),
        {"type": "error", "error": {"message": "Stream ended unexpectedly"}},
        {"type": "text", "statusCode": 503},
    ],
    ids=["401", "403", "400", "no-status", "not-an-error"],
)
def test_other_failures_keep_their_own_output(
    connected, runtime, monkeypatch, tmp_path, capsys, event  # noqa: F811
):
    failed_turn(monkeypatch, runtime, event)
    code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path)
    assert capsys.readouterr().err == ""
    assert all("/model-alternatives" not in row[1] for row in connected.calls)


def test_a_successful_turn_asks_for_no_alternatives(
    connected, runtime, monkeypatch, tmp_path, capsys  # noqa: F811
):
    assert code(monkeypatch, connected, runtime, str(uuid.uuid4()), tmp_path) == 0
    assert all("/model-alternatives" not in row[1] for row in connected.calls)
    assert capsys.readouterr().err == ""


def test_classification_reads_only_error_events():
    assert coding.model_problem("not json\n" + json.dumps(api_error(503))) == "down"
    assert coding.model_problem(json.dumps(TOO_BIG)) == "too_big"
    named = {"type": "error", "error": {"name": "ContextOverflowError", "data": {}}}
    assert coding.model_problem(json.dumps(named)) == "too_big"
    assert coding.model_problem(json.dumps({"type": "error", "error": {"status": True}})) is None
    assert coding.model_problem("") is None
