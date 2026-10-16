"""Actual host launcher orchestration, separate from up.py's demo bootstrap."""

import importlib
import json
import os
import sys
import types
import uuid
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from tests.fixtures.managed_compose import OwnedCompose, load
from tests.support.client import Browser

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.live
@pytest.mark.optional
@pytest.mark.infrastructure
def test_owned_host_runtime_launcher_preserves_state_and_stops_on_failure(
    tmp_path, report_file, monkeypatch
):
    source = Path(
        os.environ.get(
            "KEEPLANE_ORCHESTRATION_SOURCE",
            os.environ.get("KEEPLANE_INSTALLED_CLI_SOURCE", ROOT),
        )
    ).resolve(strict=True)
    image = os.environ.get("KEEPLANE_INSTALLED_CLI_IMAGE")
    if not image:
        pytest.skip("Supply an immutable cached OAuth fixture image")
    fixture = OwnedCompose(source, tmp_path, image)
    report = {
        "passed": False,
        "stage": "scope",
        "checks": [],
        "source_head": fixture.source_head,
        "app_image": image,
        "operator_file_hashes": fixture.hashes,
    }
    try:
        fixture.validate()  # No container command runs before project/volume checks.
        fixture.compose("run", "--rm", "--no-deps", "initialize")
        fixture.compose("run", "--rm", "--no-deps", "runtime-init")
        fixture.compose(
            "up", "-d", "--no-build", "--pull", "never", "--no-deps", "gateway", "model"
        )
        fixture.compose(
            "run",
            "--rm",
            "--no-deps",
            "runtime-install",
            "python",
            "manage.py",
            "migrate",
            "--noinput",
        )
        fixture.compose("up", "-d", "--no-build", "--pull", "never", "--no-deps", "app")
        fixture.ready()
        report["stage"] = "admin-registration"
        admin = Browser(fixture.server)
        status, _, _ = admin.fetch(
            "/api/session",
            {
                "username": "first-admin",
                "password": fixture.values["first-admin-password"],
            },
        )
        report["checks"].append({"name": "admin-sign-in", "status": status})
        assert status == 200
        password = "synthetic-developer-" + uuid.uuid4().hex
        status, actor, _ = admin.fetch(
            "/api/users",
            {
                "username": "orchestration-developer",
                "password": password,
                "role": "developer",
            },
        )
        report["checks"].append({"name": "create-developer", "status": status})
        assert status == 201
        status, _, _ = admin.fetch(
            "/api/models",
            {
                "name": "shared",
                "model": "fixture-coder",
                "source": "openai",
                "key_choice": "shared",
                "shared_key": fixture.values["provider-key"],
                "approved_classes": ["Confidential"],
            },
        )
        report["checks"].append({"name": "register-real-model", "status": status})
        assert status == 200
        initial_contacts = fixture.provider_status()["contacts"]
        assert initial_contacts == 1

        report["stage"] = "launcher"
        endpoint = fixture.install(["shared"])
        state = fixture.state()
        assert {row[0] for row in state["clients"]} == {
            "keeplane-cli",
            "keeplane-cli-device",
        }
        report["checks"].append(
            {"name": "actual-migration-and-fixed-clients", "passed": True}
        )

        report["stage"] = "oauth-sign-in"
        package = "orchestration_cli_" + uuid.uuid4().hex
        module = types.ModuleType(package)
        module.__path__ = [str(fixture.repo / "components/cli")]
        monkeypatch.setitem(sys.modules, package, module)
        login = importlib.import_module(package + ".browser_login")
        browser = load(
            "orchestration_browser",
            fixture.repo / "tests/fixtures/installed_cli_journey.py",
        )
        credentials = tmp_path / "synthetic-browser.json"
        credentials.write_text(
            json.dumps(
                {
                    "server": fixture.server,
                    "username": actor["username"],
                    "password": password,
                }
            )
        )
        credentials.chmod(0o600)
        monkeypatch.setenv("KEEPLANE_FIXTURE_LOGIN", str(credentials))
        form = login.authorization_code(
            fixture.server, timeout=15, browser=browser.browser
        )
        access, _ = login.exchange(fixture.server, form)
        opener = build_opener(ProxyHandler({}), login.NoRedirects())

        def request(url, payload=None, *, project=None):
            headers = {
                "Authorization": "Bearer " + access,
                "Content-Type": "application/json",
            }
            if project:
                headers.update(
                    {
                        "X-Keeplane-Project-ID": project,
                        "X-Keeplane-Installed-Runtime": "operator",
                        "X-Keeplane-Unknown": "forged",
                        "Cookie": "forged=private",
                    }
                )
            outgoing = Request(
                url,
                data=None if payload is None else json.dumps(payload).encode(),
                headers=headers,
            )
            with opener.open(outgoing, timeout=10) as response:
                assert response.status == 200
                return json.load(response)

        assert request(fixture.server + "/api/runtime/session")["id"] == actor["id"]
        project = str(uuid.uuid4())
        request(
            fixture.server + "/api/runtime/projects",
            {"project_id": project, "name": "Owned launcher"},
        )
        task = {
            "model": "shared",
            "messages": [{"role": "user", "content": "Reply OK."}],
            "max_tokens": 8,
        }
        assert request(endpoint + "/chat/completions", task, project=project)["choices"]
        assert fixture.provider_status()["contacts"] == initial_contacts + 1
        report["checks"].append(
            {"name": "actual-sign-in-and-guarded-request", "passed": True}
        )

        report["stage"] = "restart"
        fixture.install(["shared"])
        assert fixture.state() == state
        assert request(fixture.server + "/api/runtime/session")["id"] == actor["id"]
        assert request(endpoint + "/chat/completions", task, project=project)["choices"]
        assert fixture.provider_status()["contacts"] == initial_contacts + 2
        report["checks"].append(
            {"name": "credentials-account-model-and-grant-preserved", "passed": True}
        )

        report["stage"] = "forced-enrollment-failure"
        failure_start = len(fixture.launch_steps)
        with pytest.raises(RuntimeError, match="managed gateway is stopped"):
            fixture.install(["missing-owned-model"])
        failure_steps = fixture.launch_steps[failure_start:]
        assert not any("error_class" in row for row in failure_steps)
        assert [row for row in failure_steps if row["exit_code"]] == [failure_steps[-2]]
        assert failure_steps[-2]["operation"] == "install_runtime_guard"
        assert failure_steps[-1] == {
            "operation": "stop",
            "services": ["gateway"],
            "exit_code": 0,
        }
        assert (
            not fixture.running("gateway")
            and fixture.running("app")
            and fixture.running("model")
        )
        assert fixture.state() == state
        provider = fixture.provider_status()
        assert provider["contacts"] == initial_contacts + 2 and not provider["failures"]
        report["checks"].append(
            {
                "name": "only-owned-gateway-stopped-with-no-provider-contact",
                "passed": True,
            }
        )
        report.update(
            passed=True, stage="complete", provider_contacts=provider["contacts"]
        )
    except Exception as error:  # noqa: BLE001 - preserve safe diagnostics without credentials or native output.
        report["error_class"] = type(error).__name__
        if hasattr(error, "code"):
            report["http_status"] = error.code
        raise AssertionError(
            "Owned launcher failed at "
            + report["stage"]
            + " ("
            + type(error).__name__
            + ")"
        ) from None
    finally:
        report["launcher_steps"] = fixture.launch_steps
        try:
            fixture.cleanup()
            report["cleaned"] = True
        finally:
            report_file.write_text(json.dumps(report))
