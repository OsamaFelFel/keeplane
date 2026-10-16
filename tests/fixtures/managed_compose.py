"""An owned, minimal topology for the real managed launcher subprocesses."""

import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import urlopen

PYTHON = (
    "python@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a"
)
GATEWAY = "cr.agentgateway.dev/agentgateway@sha256:9d3e6044ddcdc0878b1787f77bd401252b95e22684203fb5e874c4c42d2ed90c"


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OwnedCompose:
    def __init__(self, source, directory, image):
        assert image.startswith("sha256:") and len(image) == 71
        assert (source / "tests/fixtures/installed_cli_journey.py").is_file()
        assert (
            source
            / "components/control-plane/accounts/management/commands/register_cli_client.py"
        ).is_file()
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=source,
            capture_output=True,
            text=True,
            check=True,
        )
        self.source_head = revision.stdout.strip()
        self.repo, self.image = directory / "repo", image
        self.repo.mkdir()
        self.project = "keeplane-orchestration-" + uuid.uuid4().hex[:10]
        self.app_port, self.runtime_port = port(), port()
        while self.runtime_port == self.app_port:
            self.runtime_port = port()
        self.server = "http://127.0.0.1:" + str(self.app_port)
        for folder in (
            "components/control-plane",
            "components/cli",
            "deploy/local",
            "tests/fixtures",
        ):
            shutil.copytree(
                source / folder,
                self.repo / folder,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"),
            )
        for path in (self.repo, *self.repo.rglob("*")):
            path.chmod(0o755 if path.is_dir() else 0o644)
        self.credentials = self.repo / "credentials"
        self.credentials.mkdir(mode=0o700)
        self.values = {
            name: secrets.token_urlsafe(32)
            for name in (
                "first-admin-password",
                "gateway-admin-key",
                "gateway-runtime-key",
                "provider-key",
            )
        }
        for name, value in self.values.items():
            path = self.credentials / name
            path.write_text(value)
            path.chmod(0o600)
        self.runtime = self.repo / "runtime"
        self.runtime.mkdir(mode=0o700)
        (self.runtime / ".env").write_text("KEEPLANE_PORT=" + str(self.app_port) + "\n")
        self.env = dict(
            os.environ,
            COMPOSE_PROJECT_NAME=self.project,
            KEEPLANE_PORT=str(self.app_port),
            KEEPLANE_RUNTIME_PORT=str(self.runtime_port),
            KEEPLANE_RUNTIME_APP_IMAGE=image,
            KEEPLANE_RUNTIME_OAUTH_ENABLED="1",
        )
        init = """import os,shutil
from pathlib import Path
from prepare_volumes import prepare
prepare()
os.chown('/data',65532,65532)
shutil.copyfile('/host-secrets/provider-key','/provider-keys/fixture-expected')
os.chmod('/provider-keys/fixture-expected',0o600)
os.chown('/provider-keys/fixture-expected',65532,65532)
"""
        provider = """from pathlib import Path
from http.server import ThreadingHTTPServer
from tests.fixtures.installed_cli_provider import InstalledCliProvider
InstalledCliProvider.grant=Path('/provider-keys/fixture-expected').read_text().strip()
ThreadingHTTPServer(('0.0.0.0',18080),InstalledCliProvider).serve_forever()
"""
        services = {
            "initialize": {
                "image": PYTHON,
                "user": "0",
                "command": ["python", "-c", init],
                "volumes": [
                    "account-data:/state",
                    "provider-keys:/provider-keys",
                    "app-secrets:/secrets",
                    "gateway-data:/data",
                    "./credentials:/host-secrets:ro",
                    "./deploy/local/prepare_volumes.py:/prepare_volumes.py:ro",
                ],
            },
            "model": {
                "image": PYTHON,
                "user": "65532:65532",
                "command": ["python", "-c", provider],
                "environment": {"PYTHONPATH": "/repo", "PYTHONDONTWRITEBYTECODE": "1"},
                "volumes": [
                    "./tests:/repo/tests:ro",
                    "provider-keys:/provider-keys:ro",
                ],
            },
            "gateway": {
                "image": GATEWAY,
                "command": ["-f", "/installed/gateway.json"],
                "volumes": ["gateway-data:/data", "provider-keys:/provider-keys:ro"],
            },
            "app": {
                "image": image,
                "working_dir": "/app",
                "command": [
                    "python",
                    "-m",
                    "gunicorn",
                    "--config",
                    "config/gunicorn.conf.py",
                    "config.wsgi:application",
                ],
                "environment": {
                    "GATEWAY_URL": "http://gateway:4000",
                    "GATEWAY_ADMIN_KEY_FILE": "/run/secrets/gateway-admin-key",
                    "GATEWAY_RUNTIME_KEY_FILE": "/run/secrets/gateway-runtime-key",
                    "FIRST_ADMIN_PASSWORD_FILE": "/run/secrets/first-admin-password",
                    "PUBLIC_ORIGIN": self.server,
                    "PROVIDER_KEY_DIR": "/provider-keys",
                    "PREVIEW_OPENAI_BASE_URL": "http://model:18080/v1",
                    "PYTHONPATH": "/app:/opt/oauth",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                "volumes": [
                    "./components/control-plane:/app:ro",
                    "account-data:/state",
                    "provider-keys:/provider-keys",
                    "app-secrets:/run/secrets:ro",
                ],
                "ports": ["127.0.0.1:" + str(self.app_port) + ":3000"],
                "tmpfs": ["/tmp:uid=65532,gid=65532,mode=700"],
            },
            "runtime-install": {
                "working_dir": "/app",
                "environment": {
                    "PYTHONPATH": "/app:/opt/oauth",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            },
        }
        for service in services.values():
            service.update(
                pull_policy="never",
                read_only=True,
                security_opt=["no-new-privileges:true"],
            )
        self.base = self.repo / "compose.yaml"
        self.base.write_text(
            json.dumps(
                {
                    "name": "keeplane-local",
                    "services": services,
                    "volumes": {
                        name: {}
                        for name in (
                            "account-data",
                            "provider-keys",
                            "app-secrets",
                            "gateway-data",
                        )
                    },
                    "networks": {"default": {"internal": True}},
                }
            )
        )
        self.prefix = [
            "docker",
            "compose",
            "--env-file",
            str(self.runtime / ".env"),
            "-f",
            str(self.base),
            "-f",
            str(self.repo / "deploy/local/runtime.yaml"),
        ]
        self.launcher = load(
            "owned_guarded_runtime", self.repo / "deploy/local/guarded_runtime.py"
        )
        self.launch_steps = []
        self.hashes = {
            name: hashlib.sha256(
                (self.repo / "deploy/local" / name).read_bytes()
            ).hexdigest()
            for name in (
                "guarded_runtime.py",
                "runtime.yaml",
                "prepare_runtime.py",
                "runtime-base.json",
            )
        }

        def observed(command, **kwargs):
            arguments = command[len(self.prefix) :]
            step = next(
                (
                    name
                    for name in (
                        "migrate",
                        "register_cli_client",
                        "install_runtime_guard",
                    )
                    if name in arguments
                ),
                arguments[0] if arguments else "unknown",
            )
            row = {"operation": step}
            if step == "stop":
                row["services"] = arguments[1:]
            self.launch_steps.append(row)
            try:
                result = subprocess.run(command, **kwargs)  # noqa: PLW1510 - preserve the original helper's explicit check argument.
                row["exit_code"] = result.returncode
                return result
            except (OSError, subprocess.TimeoutExpired) as error:
                row["error_class"] = type(error).__name__
                raise

        # Observe only safe operation/status metadata; execute every original
        # subprocess with exactly its supplied arguments and environment.
        self.launcher.subprocess = SimpleNamespace(
            run=observed, TimeoutExpired=subprocess.TimeoutExpired
        )
        self.validated = False

    def command(self, args, *, timeout=120):
        result = subprocess.run(
            args,
            cwd=self.repo,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode:
            raise RuntimeError("Owned Compose command failed")
        return result.stdout.strip()

    def compose(self, *args):
        return self.command(self.prefix + list(args))

    def validate(self):
        config = json.loads(
            self.compose("--profile", "*", "config", "--format", "json")
        )
        assert {"runtime-init", "runtime-install"} <= config["services"].keys()
        assert config["name"] == self.project
        assert all(
            not row.get("external") and row["name"].startswith(self.project + "_")
            for row in config["volumes"].values()
        )
        assert "keeplane-accounts-trial_model-approvals" not in json.dumps(config)
        assert all(
            not row.get("external")
            and row["name"].startswith(self.project + "_")
            and row.get("internal")
            for row in config["networks"].values()
        )
        for name, service in config["services"].items():
            assert not service.get("build") and not service.get("container_name")
            for binding in service.get("ports", []):
                assert binding["host_ip"] == "127.0.0.1"
                assert (name, binding["target"]) in {("app", 3000), ("gateway", 5000)}
            for volume in service.get("volumes", []):
                if volume["type"] == "bind":
                    assert (
                        Path(volume["source"])
                        .resolve()
                        .is_relative_to(self.repo.resolve())
                    )
        self.validated = True

    def ready(self):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                remaining = max(0.01, deadline - time.monotonic())
                with urlopen(
                    self.server + "/health/ready", timeout=min(2, remaining)
                ) as response:
                    assert response.status == 200
                remaining = max(0.01, deadline - time.monotonic())
                with urlopen(
                    self.server + "/health", timeout=min(3, remaining)
                ) as response:
                    if response.status == 200:
                        return
            except (OSError, AssertionError):
                time.sleep(0.1)
        raise RuntimeError("Owned application did not become ready")

    def install(self, models):
        return self.launcher.install(
            self.repo,
            self.runtime,
            models,
            self.runtime_port,
            env=self.env,
            wait_ready=self.ready,
            app_image=self.image,
        )

    def provider_status(self):
        return json.loads(
            self.compose(
                "exec",
                "-T",
                "model",
                "python",
                "-c",
                "import json,urllib.request;print(urllib.request.urlopen('http://127.0.0.1:18080/fixture/status').read().decode())",
            )
        )

    def running(self, service):
        identifier = self.compose("ps", "-aq", service)
        return (
            identifier
            and self.command(
                ["docker", "inspect", identifier, "--format", "{{.State.Running}}"]
            )
            == "true"
        )

    def state(self):
        script = """import os,json,hashlib
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
import django;django.setup()
from pathlib import Path
from accounts.models import User
from model_registry.models import ModelApproval
from oauth2_provider.models import Application
paths=[Path('/run/secrets')/name for name in ('first-admin-password','gateway-admin-key','gateway-runtime-key')]+[Path('/state/django-secret-key'),Path('/installed/callback-key')]
result={'credentials':[hashlib.sha256(path.read_bytes()).hexdigest() for path in paths], 'users':list(User.objects.order_by('id').values_list('id','username')), 'model':list(ModelApproval.objects.filter(pk='shared').values_list('gateway_fingerprint','key_choice')), 'clients':list(Application.objects.order_by('client_id').values_list('client_id','authorization_grant_type'))}
print(json.dumps(result,default=str))
"""
        return json.loads(self.compose("exec", "-T", "app", "python", "-c", script))

    def failure_diagnostics(self, directory):
        """Keep raw owned logs private; return only statuses and error classes."""
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        observations = {}
        for path in ("/health/ready", "/health"):
            try:
                with urlopen(self.server + path, timeout=2) as response:
                    observations[path] = {"status": response.status}
            except HTTPError as error:
                observations[path] = {"status": error.code}
                error.close()
            except OSError as error:
                observations[path] = {"error_class": type(error).__name__}
        for service in ("app", "gateway"):
            identifier = self.compose("ps", "-aq", service)
            state = json.loads(
                self.command(
                    ["docker", "inspect", identifier, "--format", "{{json .State}}"]
                )
            )
            logs = self.compose("logs", "--no-color", "--tail", "100", service)
            private = directory / (service + ".log")
            private.write_text(logs)
            private.chmod(0o600)
            observations[service] = {
                "running": state["Running"],
                "exit_code": state["ExitCode"],
                "oom": state["OOMKilled"],
                "exception_classes": sorted(
                    set(
                        re.findall(
                            r"^([A-Za-z_]\w*(?:Error|Exception)):", logs, re.MULTILINE
                        )
                    )
                ),
            }
        return observations

    def cleanup(self):
        if self.validated:
            self.compose("down", "--volumes", "--remove-orphans")
            assert not self.command(
                [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    "label=com.docker.compose.project=" + self.project,
                ]
            )
            assert not self.command(
                [
                    "docker",
                    "volume",
                    "ls",
                    "-q",
                    "--filter",
                    "label=com.docker.compose.project=" + self.project,
                ]
            )
