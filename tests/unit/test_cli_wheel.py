"""Offline wheel installation and executable behavior, away from source imports."""

import email
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from tests.unit import test_cli_browser_login as browser_cases

issuer = browser_cases.issuer
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.optional
def test_offline_wheel_install_commands_and_instruction_resources(tmp_path, issuer):
    configured = os.environ.get("KEEPLANE_CLI_BUILD_PYTHON")
    if not configured:
        pytest.skip(
            "Set KEEPLANE_CLI_BUILD_PYTHON to a Python with the pinned build backend"
        )
    python = Path(configured).absolute()
    assert python.is_file(), "The explicitly configured CLI build Python is unavailable"
    stage, away, wheels = (tmp_path / name for name in ("source", "away", "wheels"))
    stage.mkdir()
    away.mkdir()
    sources = [
        ROOT / "pyproject.toml",
        ROOT / "LICENSE",
        ROOT / "components/cli/README.md",
    ]
    sources += list((ROOT / "components/cli").glob("*.py"))
    sources += [
        ROOT / "components/cli/instruction_plugin" / name
        for name in ("index.js", "package.json")
    ]
    for source in sources:
        target = stage / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    environment = {
        name: value
        for name, value in os.environ.items()
        if name in {"PATH", "HOME", "LANG", "LC_ALL", "SYSTEMROOT"}
    }
    environment.update(
        PIP_CONFIG_FILE=os.devnull, PIP_NO_INDEX="1", PYTHONNOUSERSITE="1"
    )

    def run(arguments, *, timeout=60):
        result = subprocess.run(
            list(map(str, arguments)),
            cwd=away,
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    assert (
        run(
            [
                python,
                "-I",
                "-c",
                "from importlib.metadata import version; print(version('setuptools'))",
            ]
        ).strip()
        == "84.0.0"
    )
    run(
        [
            python,
            "-m",
            "pip",
            "wheel",
            "--no-index",
            "--no-deps",
            "--no-build-isolation",
            "--no-cache-dir",
            "--wheel-dir",
            wheels,
            stage,
        ]
    )
    (wheel,) = wheels.glob("*.whl")
    with ZipFile(wheel) as archive:
        files = set(archive.namelist())
        code = {
            "keeplane_cli/" + path.name
            for path in (ROOT / "components/cli").glob("*.py")
        }
        resources = {
            "keeplane_cli/instruction_plugin/index.js",
            "keeplane_cli/instruction_plugin/package.json",
        }
        assert {
            name for name in files if name.startswith("keeplane_cli/")
        } == code | resources
        info = "keeplane_cli-0.0.0.dist-info/"
        assert all(name.startswith(("keeplane_cli/", info)) for name in files)
        metadata = email.message_from_bytes(archive.read(info + "METADATA"))
        assert not metadata.get_all("Requires-Dist")
        assert metadata["License-Expression"] == "Apache-2.0"
        assert (
            archive.read(info + "licenses/LICENSE") == (ROOT / "LICENSE").read_bytes()
        )
        assert (
            "keeplane = keeplane_cli.keeplane:main"
            in archive.read(info + "entry_points.txt").decode()
        )

    install = tmp_path / "installed"
    run([python, "-m", "venv", install])
    runtime = install / "bin/python"
    command = install / "bin/keeplane"
    run([runtime, "-m", "pip", "install", "--no-index", "--no-deps", wheel])
    help_text = run([command, "--help"])
    assert all(
        name in help_text
        for name in ("login", "refresh", "whoami", "logout", "code", "keys")
    )
    assert "--device" in run([command, "login", "--help"])
    assert "--instructions" in run([command, "code", "--help"])
    assert "--profile" in run([command, "refresh", "--help"])
    profile = tmp_path / "profile"
    output = run(
        [
            command,
            "login",
            "--device",
            "--server",
            issuer.url,
            "--profile",
            profile,
            "--timeout",
            "20",
        ]
    )
    assert issuer.user_code in output
    assert all(
        secret not in output
        for secret in (issuer.access, issuer.refresh, issuer.device_code)
    )
    assert (
        json.loads(run([command, "whoami", "--profile", profile]))["id"] == issuer.actor
    )
    saved = json.loads((profile / "credential.json").read_text())
    assert saved["client_id"] == "keeplane-cli-device"
    issuer.expected_refresh, issuer.refresh_client = issuer.refresh, saved["client_id"]
    issuer.access, issuer.refresh = "kpc_" + "n" * 43, "kpr_" + "m" * 43
    assert "refreshed" in run([command, "refresh", "--profile", profile])
    assert len(issuer.refresh_requests) == 1
    assert (
        json.loads((profile / "credential.json").read_text())["access_token"]
        == issuer.access
    )
    assert "removed" in run([command, "logout", "--profile", profile])
    assert issuer.revocations == 1 and not (profile / "credential.json").exists()

    # Exercise the installed adapter's actual plugin path without a native runtime/provider.
    probe = away / "resources.py"
    probe.write_text("""import json, sys
from pathlib import Path
from keeplane_cli import opencode_adapter as adapter
plugin = Path(adapter.__file__).with_name("instruction_plugin")
assert plugin.is_relative_to(Path(sys.prefix))
assert (plugin / "index.js").is_file()
assert (plugin / "package.json").is_file()
print(json.dumps({name: (plugin / name).read_text() for name in ("index.js", "package.json")}))
""")
    actual = json.loads(run([runtime, "-I", probe]))
    for name, content in actual.items():
        assert (
            hashlib.sha256(content.encode()).digest()
            == hashlib.sha256(
                (ROOT / "components/cli/instruction_plugin" / name).read_bytes()
            ).digest()
        )
    search = json.loads(
        run([runtime, "-I", "-c", "import json, sys; print(json.dumps(sys.path))"])
    )
    assert str(ROOT) not in search and str(stage) not in search
