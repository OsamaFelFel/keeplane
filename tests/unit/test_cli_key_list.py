"""The real CLI and HTTP transport print only a strict, current-account key list."""

import json
import sys
import uuid

import pytest

from components.cli import keeplane
from tests.unit.test_cli_provider_keys import api as api  # noqa: PLC0414 -- pytest fixture re-export


def command(api, monkeypatch, project=None):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "keeplane",
            "keys",
            "list",
            "--profile",
            str(api.profile),
            "--project",
            project or api.project,
        ],
    )
    return keeplane.main()


def row(name="coder", required=True, status="added"):
    return {"id": name, "own_key_required": required, "status": status}


def test_lists_current_account_metadata_without_writing_profile(
    api, monkeypatch, capsys
):
    original = {p.name: p.read_bytes() for p in api.profile.iterdir()}
    api.key_list = [row(), row("shared", False, None)]
    assert command(api, monkeypatch) == 0
    assert json.loads(capsys.readouterr().out) == {
        "project_id": api.project,
        "models": api.key_list,
    }
    assert [c[1] for c in api.calls] == [
        "/api/runtime/session",
        f"/api/runtime/projects/{api.project}/provider-keys",
    ]
    assert all(
        c[0] == "GET"
        and c[2]["Authorization"] == "Bearer " + api.access
        and "Cookie" not in c[2]
        for c in api.calls
    )
    assert original == {p.name: p.read_bytes() for p in api.profile.iterdir()}
    api.key_list = []
    assert command(api, monkeypatch) == 0
    assert json.loads(capsys.readouterr().out)["models"] == []


@pytest.mark.parametrize("fault", ["actor", "401", "503"])
def test_current_account_failure_prevents_listing(api, monkeypatch, capsys, fault):
    if fault == "actor":
        api.actor = str(uuid.uuid4())
    else:
        api.account_status = int(fault)
    assert command(api, monkeypatch) == 1
    assert len(api.calls) == 1
    output = capsys.readouterr()
    assert (
        api.access not in output.out + output.err
        and api.refresh not in output.out + output.err
    )


@pytest.mark.parametrize(
    "rows",
    [
        [row(status="refused")],
        [row(status="healthy")],
        [row(status=[])],
        [row(required=1)],
        [row(required=False)],
        [row(required=True, status=None)],
        [row(name="")],
        [row(name="x" * 257)],
        [row(name="bad\nname")],
        [row(), row()],
        [row("z"), row("a")],
        [{**row(), "key": "do-not-print"}],
    ],
)
def test_unknown_status_or_malformed_rows_are_not_printed(
    api, monkeypatch, capsys, rows
):
    api.key_list = rows
    assert command(api, monkeypatch) == 1
    output = capsys.readouterr()
    assert not output.out and "invalid key list" in output.err
    assert "do-not-print" not in output.err


@pytest.mark.parametrize("fault", ["project", "extra", "duplicate", "oversized"])
def test_response_binding_duplicates_and_size_are_checked(
    api, monkeypatch, capsys, fault
):
    api.list_response = {"project_id": api.project, "models": []}
    if fault == "project":
        api.list_response["project_id"] = str(uuid.uuid4())
    elif fault == "extra":
        api.list_response["secret"] = "do-not-print"
    elif fault == "duplicate":
        api.list_response = (
            '{"project_id":"' + api.project + '","models":[],"models":[]}'
        ).encode()
    else:
        api.list_response["models"] = [row("x" * (1024 * 1024))]
    assert command(api, monkeypatch) == 1
    output = capsys.readouterr()
    assert not output.out and "do-not-print" not in output.err


def test_invalid_project_is_rejected_and_saved_credentials_redacted(
    api, monkeypatch, capsys
):
    assert command(api, monkeypatch, project="not-a-uuid") == 1
    assert not api.calls
    capsys.readouterr()
    api.key_list = [row(api.access)]
    assert command(api, monkeypatch) == 0
    output = capsys.readouterr()
    assert api.access not in output.out and api.refresh not in output.out
