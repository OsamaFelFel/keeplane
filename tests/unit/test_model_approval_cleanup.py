"""The live journey owns its temporary model, including partial-failure cleanup."""

from copy import deepcopy
from io import BytesIO
import json
from types import SimpleNamespace

import pytest

from tests.e2e import test_model_approval as journey


@pytest.mark.parametrize("failure", [None, "creation", "creation_reply", "partial_setup", "restart", "approval_cleanup"])
def test_dynamic_fixture_preserves_existing_approval(monkeypatch, tmp_path, failure):
    original = {"approved": True, "key_choice": "none", "approved_classes": [],
                "owned_by_keeplane": True, "gateway_fingerprint": "original-revision"}
    registry = {"local-fixture": {}, "second-local": {"original": True}}
    approvals = {"second-local": deepcopy(original)}
    initial_registry, initial_approvals = deepcopy(registry), deepcopy(approvals)
    temporary = []
    password = tmp_path / "first-admin-password"
    password.write_text("synthetic-first-admin-password")
    monkeypatch.setattr(journey, "RUNTIME", tmp_path)
    monkeypatch.setattr(journey, "REPORT", tmp_path / "report.json")
    monkeypatch.setattr(journey.time, "sleep", lambda _: None)

    class Browser:
        opener = SimpleNamespace(open=lambda *_args, **_kwargs: BytesIO(b'<div id="root">'))

        def login(self, *_args):
            return (200,)

        def fetch(self, path, payload=None, action=True, method=None):
            if not action:
                return 403, {}, None
            if path == "/api/models":
                return 200, {"models": [
                    {"id": name, **deepcopy(approvals.get(name, {
                        "approved": False, "key_choice": None,
                        "approved_classes": [], "owned_by_keeplane": False}))}
                    for name in registry]}, None
            if path == "/api/ask":
                return (200, {"answer": "mock answer"}, None) if payload["model"] in approvals else (403, {}, None)
            name = path.split("/")[3]
            if method == "DELETE":
                if name in temporary and failure == "approval_cleanup":
                    raise RuntimeError("Approval cleanup failed")
                return (200 if approvals.pop(name, None) else 404), {"gateway_model_preserved": True}, None
            if payload["key_choice"] == "shared" or "Restricted" in payload["approved_classes"]:
                return 400, {}, None
            approvals[name] = {"approved": True, "owned_by_keeplane": False, **deepcopy(payload)}
            if name in temporary and failure == "partial_setup":
                raise ConnectionError("Reply lost after saving temporary approval")
            return 200, {}, None

    def gateway(method, path, payload=None):
        if method == "PUT":
            model = payload["resources"][0]["value"]
            name = model["name"]
            assert name not in registry
            registry[name] = deepcopy(model)
            temporary.append(name)
            if failure == "creation_reply":
                raise ConnectionError("Reply lost after creating temporary model")
            return (500 if failure == "creation" else 200), {}
        name = path.rsplit("/", 1)[1]
        return (200 if registry.pop(name, None) else 404), {}

    restarts = []

    def restart(_base):
        restarts.append(True)
        if failure == "restart" and len(restarts) == 2:
            raise RuntimeError("Restart check failed")

    monkeypatch.setattr(journey, "Browser", Browser)
    monkeypatch.setattr(journey, "gateway_call", gateway)
    monkeypatch.setattr(journey, "restart_app", restart)
    if failure == "approval_cleanup":
        with pytest.raises(SystemExit):
            journey.run_cases()
    elif failure:
        with pytest.raises((RuntimeError, ConnectionError)):
            journey.run_cases()
    else:
        journey.run_cases()
    assert len(temporary) == 1
    assert registry == initial_registry
    assert approvals["second-local"] == initial_approvals["second-local"]
    if failure == "approval_cleanup":
        assert json.loads(journey.REPORT.read_text())["cleanup"].startswith("failed:")
    else:
        assert approvals == initial_approvals
