"""Remote command failures stay failures without exposing private command data."""

import json
import os
import subprocess
import sys
import textwrap
import uuid

import pytest

from tests.support import gateway


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (
            ("ConnectionRefusedError: synthetic-private-value\n"
             "urllib.error.URLError: synthetic-private-value\n"),
            ["ConnectionRefusedError", "URLError"],
        ),
        ("error: synthetic-private-value\n", []),
    ],
    ids=["python-transport", "container-exec"],
)
def test_failed_command_reports_only_exit_and_exception_types(
    monkeypatch, tmp_path, stderr, expected
):
    monkeypatch.setenv("KEEPLANE_BASE_URL", "http://127.0.0.1:3000")
    monkeypatch.setenv("KEEPLANE_TEST_REPORT_DIR", str(tmp_path))

    def failed(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 1, stdout="synthetic-private-value", stderr=stderr
        )

    monkeypatch.setattr(gateway.subprocess, "run", failed)
    with pytest.raises(RuntimeError) as observed:
        gateway.app_exec("python", "-c", "synthetic-private-command")
    reports = list(tmp_path.glob("gateway-command-*.json"))
    assert len(reports) == 1
    assert json.loads(reports[0].read_text()) == {
        "failed": True,
        "kind": "remote_exit",
        "exit_code": 1,
        "remote_exception_types": expected,
    }
    combined = str(observed.value) + reports[0].read_text()
    assert "synthetic-private-value" not in combined
    assert "synthetic-private-command" not in combined


def test_command_timeout_hides_command_and_captured_output(monkeypatch, tmp_path):
    monkeypatch.setenv("KEEPLANE_BASE_URL", "http://127.0.0.1:3000")
    monkeypatch.setenv("KEEPLANE_TEST_REPORT_DIR", str(tmp_path))

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(
            command, 30, output="synthetic-private-value", stderr="synthetic-private-value"
        )

    monkeypatch.setattr(gateway.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="timeout after 30 seconds") as observed:
        gateway.app_exec("python", "-c", "synthetic-private-command")
    report = next(tmp_path.glob("gateway-command-*.json"))
    assert json.loads(report.read_text())["kind"] == "command_timeout"
    assert "synthetic-private-value" not in str(observed.value) + report.read_text()
    assert "synthetic-private-command" not in str(observed.value)
    assert observed.value.__suppress_context__


def test_default_pytest_traceback_hides_private_command_and_put_payload(tmp_path):
    private = uuid.uuid4().hex
    fixture = tmp_path / "test_private_traceback.py"
    fixture.write_text(textwrap.dedent('''\
        import os
        import subprocess
        import pytest
        from tests.support import gateway

        @pytest.mark.parametrize("operation", ["direct", "put"])
        @pytest.mark.parametrize("failure", ["exit", "timeout"])
        def test_command_failure(monkeypatch, operation, failure):
            def failed(command, **kwargs):
                if failure == "timeout":
                    raise subprocess.TimeoutExpired(
                        command, 30, output=os.environ["PRIVATE_DIAGNOSTIC_CONTROL"],
                        stderr=os.environ["PRIVATE_DIAGNOSTIC_CONTROL"],
                    )
                return subprocess.CompletedProcess(
                    command, 1, stdout=os.environ["PRIVATE_DIAGNOSTIC_CONTROL"],
                    stderr="URLError: " + os.environ["PRIVATE_DIAGNOSTIC_CONTROL"],
                )
            monkeypatch.setattr(gateway.subprocess, "run", failed)
            if operation == "put":
                gateway.gateway_call("PUT", "/api/config/resources/llm.model", {
                    "api_key": os.environ["PRIVATE_DIAGNOSTIC_CONTROL"],
                })
            else:
                gateway.app_exec("python", "-c", os.environ["PRIVATE_DIAGNOSTIC_CONTROL"])
        '''))
    environment = {
        **os.environ,
        "PYTHONPATH": str(gateway.REPO),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTEST_ADDOPTS": "",
        "KEEPLANE_BASE_URL": "http://127.0.0.1:3000",
        "KEEPLANE_TEST_REPORT_DIR": str(tmp_path / "reports"),
        "PRIVATE_DIAGNOSTIC_CONTROL": private,
    }
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", os.devnull, "-q", "--tb=long", str(fixture)],
        check=False, cwd=gateway.REPO, env=environment, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1
    assert "4 failed" in result.stdout
    assert "Private gateway test command failed" in result.stdout
    assert private not in result.stdout + result.stderr
    reports = list((tmp_path / "reports").glob("gateway-command-*.json"))
    assert len(reports) == 4
    assert all(private not in report.read_text() for report in reports)
