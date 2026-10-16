"""Installed wheel → actual OAuth/installer/native gateway; synthetic provider only."""

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGES = json.loads((ROOT / "deploy/local/stack.lock.json").read_text())["images"]
pytestmark = pytest.mark.optional


def configured(name):
    value = os.environ.get(name)
    if not value:
        if os.environ.get("KEEPLANE_INSTALLED_CLI_REQUIRED") == "1":
            pytest.fail("The required installed CLI fixture is not configured: " + name)
        pytest.skip("Configure the explicit installed CLI trial: " + name)
    return value


def test_installed_oauth_coding_tools_resume_refresh_logout(tmp_path):
    source = Path(configured("KEEPLANE_INSTALLED_CLI_SOURCE")).resolve(strict=True)
    image = configured("KEEPLANE_INSTALLED_CLI_IMAGE")
    wheel = Path(configured("KEEPLANE_INSTALLED_CLI_WHEEL")).resolve(strict=True)
    wheel_digest = configured("KEEPLANE_INSTALLED_CLI_WHEEL_SHA256")
    binary = Path(configured("KEEPLANE_OPENCODE_V2_BIN")).resolve(strict=True)
    assert image.startswith("sha256:") and len(image) == 71
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() == wheel_digest
    native_digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    assert (
        native_digest
        == "a2dee30005064075c216fdcc3fcaba7071c81b39d00b4286206faa50e461b61d"
    )
    assert (source / "tests/fixtures/installed_runtime.py").is_file()
    fixtures = [
        "installed_cli_journey.py",
        "installed_cli_provider.py",
        "installed_cli_server.py",
        "installed_cli_tls.py",
    ]
    for filename in fixtures + ["cli_coding_provider.py"]:
        assert (source / "tests/fixtures" / filename).read_bytes() == (
            ROOT / "tests/fixtures" / filename
        ).read_bytes(), "The immutable fixture source differs from the tested revision"

    trial = tmp_path / "trial"
    trial.mkdir(mode=0o700)
    tls = trial / "tls"
    tls.mkdir(mode=0o700)
    project = "keeplane-installed-cli-" + uuid.uuid4().hex[:10]
    report = {
        "passed": False,
        "app_image": image,
        "wheel_sha256": wheel_digest,
        "native_sha256": native_digest,
        "client_separate_network_namespace": True,
        "read_only_root": True,
        "uid": 65532,
        "external_network": False,
    }
    private = {
        "runtime-key": secrets.token_urlsafe(32),
        "admin-key": secrets.token_urlsafe(32),
        "callback-key": secrets.token_urlsafe(32),
        "first-admin": secrets.token_urlsafe(32),
        "signing": secrets.token_urlsafe(64),
        "provider-seed": secrets.token_urlsafe(32),
    }
    for name, value in private.items():
        (trial / name).write_text(value)
        (trial / name).chmod(0o600)
    base_config = {
        "config": {
            "adminAddr": "127.0.0.1:15000",
            "storage": {"mode": "hybrid"},
            "database": {"url": "sqlite:///data/gateway.db"},
        },
        "gateways": {"default": {"port": 4000}},
        "ui": {"gateways": "default", "policies": {}},
        "llm": {"models": [], "policies": {}},
    }
    for section, name in (("ui", "admin-key"), ("llm", "runtime-key")):
        base_config[section]["policies"]["apiKey"] = {
            "mode": "strict",
            "keys": [
                {
                    "keyHash": "sha256:"
                    + hashlib.sha256(private[name].encode()).hexdigest()
                }
            ],
        }
    for name, data in (
        ("gateway.json", base_config),
        ("trusted.json", base_config),
        ("manifest.json", {"version": 2, "enabled": False}),
    ):
        (trial / name).write_text(json.dumps(data))
        (trial / name).chmod(0o600)

    def command(label, arguments, *, input=None, timeout=40, check=True):
        report["stage"] = label
        process = subprocess.run(
            arguments, input=input, capture_output=True, timeout=timeout, check=False
        )
        for extension, output in (
            ("stdout", process.stdout),
            ("stderr", process.stderr),
        ):
            path = trial / (label + "." + extension)
            path.write_bytes(output)
            path.chmod(0o600)
        if check and process.returncode:
            raise RuntimeError("Owned installed CLI fixture failed: " + label)
        return process

    openssl = shutil.which("openssl")
    assert openssl, "The explicit TLS fixture requires openssl to create a synthetic CA"
    command(
        "synthetic-certificate",
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(tls / "key.pem"),
            "-out",
            str(tls / "cert.pem"),
            "-days",
            "1",
            "-subj",
            "/CN=front",
            "-addext",
            "subjectAltName=DNS:front",
        ],
        timeout=15,
    )
    (tls / "cert.pem").chmod(
        0o644
    )  # Public trust anchor; only this file reaches the client.
    initialize = """import os,shutil
from pathlib import Path
for target in ('/installed','/tls-private'):
 p=Path(target);os.chown(p,65532,65532);p.chmod(0o700)
for name in ('runtime-key','admin-key','callback-key','first-admin','signing','provider-seed','gateway.json','trusted.json','manifest.json'):
 p=Path('/installed')/name;shutil.copyfile(Path('/trial')/name,p);p.chmod(0o600);os.chown(p,65532,65532)
for name in ('cert.pem','key.pem'):
 p=Path('/tls-private')/name;shutil.copyfile(Path('/trial/tls')/name,p);p.chmod(0o600);os.chown(p,65532,65532)
"""
    services = {
        "init": {
            "image": IMAGES["python_fixture"],
            "user": "0",
            "network_mode": "none",
            "entrypoint": ["python", "-c", initialize],
            "volumes": [
                str(trial) + ":/trial:ro",
                "installed:/installed",
                "tls-private:/tls-private",
            ],
        },
        "gateway": {
            "image": IMAGES["agentgateway"],
            "command": ["-f", "/installed/gateway.json"],
            "depends_on": {"init": {"condition": "service_completed_successfully"}},
            "volumes": ["installed:/installed:ro"],
            "tmpfs": ["/data:uid=65532,gid=65532,mode=700"],
        },
        "server": {
            "image": image,
            "command": ["python", "/source/tests/fixtures/installed_cli_server.py"],
            "network_mode": "service:gateway",
            "depends_on": ["gateway"],
            "volumes": [str(source) + ":/source:ro", "installed:/installed"],
            "tmpfs": ["/state:uid=65532,gid=65532,mode=700"],
            "environment": {
                "PYTHONPATH": "/source/components/control-plane:/source:/opt/oauth",
                "PYTHONDONTWRITEBYTECODE": "1",
                "KEEPLANE_SQLITE_PATH": "/state/keeplane.db",
                "DJANGO_SECRET_KEY_FILE": "/installed/signing",
                "FIRST_ADMIN_PASSWORD_FILE": "/installed/first-admin",
                "PUBLIC_ORIGIN": "https://front:8443",
                "GATEWAY_URL": "http://127.0.0.1:4000",
                "GATEWAY_ADMIN_KEY_FILE": "/installed/admin-key",
                "GATEWAY_RUNTIME_KEY_FILE": "/installed/runtime-key",
                "RUNTIME_AUTHORIZER_KEY_FILE": "/installed/callback-key",
                "RUNTIME_GUARD_MANIFEST_FILE": "/installed/manifest.json",
                "GATEWAY_FILE_CONFIG": "/installed/gateway.json",
                "GATEWAY_MODE": "managed",
                "PROVIDER_KEY_DIR": "/installed",
                "KEY_NAME": "provider-seed",
                "KEEPLANE_CLI_OAUTH_ENABLED": "1",
                "PREVIEW_OPENAI_BASE_URL": "http://127.0.0.1:18080/v1",
            },
        },
        "front": {
            "image": IMAGES["python_fixture"],
            "command": ["python", "/tls.py"],
            "depends_on": ["gateway"],
            "volumes": [
                "tls-private:/tls-private:ro",
                str(source / "tests/fixtures/installed_cli_tls.py") + ":/tls.py:ro",
            ],
        },
        "client": {
            "image": image,
            "command": ["python", "-c", "from threading import Event;Event().wait()"],
            "environment": {
                "SSL_CERT_FILE": "/ca/cert.pem",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            "tmpfs": [
                "/client:uid=65532,gid=65532,mode=700,exec",
                "/tmp:mode=1777,exec",
            ],
            "volumes": [
                str(wheel) + ":/package/keeplane.whl:ro",
                str(binary) + ":/runtime/opencode:ro",
                str(tls / "cert.pem") + ":/ca/cert.pem:ro",
                str(source / "tests/fixtures/installed_cli_journey.py")
                + ":/journey.py:ro",
            ],
        },
    }
    for name, service in services.items():
        service.update(
            pull_policy="never", read_only=True, security_opt=["no-new-privileges:true"]
        )
        if name != "init":
            service.update(user="65532:65532", cap_drop=["ALL"])
    assert "network_mode" not in services["client"]
    assert all(":/installed:" not in mount for mount in services["client"]["volumes"])
    compose = trial / "compose.json"
    compose.write_text(
        json.dumps(
            {
                "services": services,
                "volumes": {"installed": {}, "tls-private": {}},
                "networks": {"default": {"internal": True}},
            }
        )
    )
    dc = ["docker", "compose", "-p", project, "-f", str(compose)]
    try:
        command("start", dc + ["up", "-d"], timeout=45)
        command(
            "ready",
            dc
            + [
                "exec",
                "-T",
                "server",
                "python",
                "-c",
                "from pathlib import Path\nimport time\nfor _ in range(900):\n if Path('/state/ready.json').is_file():break\n time.sleep(.1)\nelse:raise RuntimeError('Installer/issuer fixture was not ready')",
            ],
            timeout=95,
        )
        seed = json.loads(
            command(
                "seed", dc + ["exec", "-T", "server", "cat", "/state/ready.json"]
            ).stdout
        )
        seed["wheel_sha256"] = wheel_digest
        result = command(
            "journey",
            dc + ["exec", "-T", "client", "python", "/journey.py"],
            input=json.dumps(seed).encode(),
            timeout=180,
            check=False,
        )
        report["journey"] = json.loads(result.stdout)
        if result.returncode:
            command(
                "client-command-failure",
                dc + ["exec", "-T", "client", "cat", "/client/command-failure.json"],
                check=False,
            )
        assert result.returncode == 0 and report["journey"]["passed"], (
            "Installed CLI journey failed; see the private stage report"
        )
        report["journey_passed"] = True
    except Exception as error:
        report["failed_stage"] = report["stage"]
        report["error_class"] = type(error).__name__
        raise
    finally:
        try:
            command("server-logs", dc + ["logs", "--no-color", "server"], check=False)
            cleanup = command(
                "cleanup",
                dc + ["down", "--volumes", "--remove-orphans"],
                timeout=40,
                check=False,
            )
            remaining = command(
                "remaining",
                [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    "label=com.docker.compose.project=" + project,
                ],
                check=False,
            )
            report["cleaned"] = (
                cleanup.returncode == remaining.returncode == 0
                and not remaining.stdout.strip()
            )
        except (OSError, subprocess.TimeoutExpired):
            report["cleaned"] = False
        finally:
            report["passed"] = bool(
                report.get("journey_passed") and report.get("cleaned")
            )
            (tmp_path / "installed-cli-report.json").write_text(json.dumps(report))
    assert report["cleaned"]
