"""Disposable synthetic-only native gateway fixture for focused capability checks."""

import json
import os
import secrets
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
IMAGES = json.loads((ROOT / "deploy/local/stack.lock.json").read_text())["images"]


@contextmanager
def native_runtime_trial(tmp_path, existing, config, *, fallback=False, protocol=False):
    project = "keeplane-native-" + uuid.uuid4().hex[:10]
    trial = tmp_path / "trial"
    trial.mkdir(mode=0o755)
    names = ["key-" + uuid.uuid4().hex for _ in range(2)]
    provider_key = secrets.token_urlsafe(32)
    values = {
        "admin": secrets.token_urlsafe(32),
        "gateway-key": secrets.token_urlsafe(32),
        "first-admin": secrets.token_urlsafe(32),
        "signing": secrets.token_urlsafe(64),
        "provider-expected": provider_key,
        names[0]: provider_key,
        names[1]: provider_key,
    }
    for name, value in values.items():
        (trial / name).write_text(value)
        (trial / name).chmod(0o644)
    (trial / "gateway.yaml").write_text(json.dumps(config(existing, values["admin"])))

    def command(*args, **kwargs):
        result = subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=90, **kwargs
        )
        detail = result.stderr
        for value in values.values():
            detail = detail.replace(value, "[redacted]")
        assert result.returncode == 0, "Disposable native fixture failed: " + detail
        return result.stdout

    image = command(
        "docker",
        "image",
        "inspect",
        os.environ.get("KEEPLANE_RUNTIME_FIXTURE_IMAGE", IMAGES["app_docker"]),
        "--format",
        "{{.Id}}",
    ).strip()
    mounts = [str(trial) + ":/trial:ro"]
    services = {
        "gateway": {
            "image": IMAGES["agentgateway"],
            "command": ["-f", "/trial/gateway.yaml"],
            "volumes": mounts,
            "tmpfs": ["/data:uid=65532,gid=65532,mode=700"],
        },
        "fixture": {
            "image": image,
            "command": ["python", "/fixture.py", "serve"],
            "network_mode": "service:gateway",
            "depends_on": ["gateway"],
            "tmpfs": ["/state:uid=65532,gid=65532,mode=700"],
            "volumes": mounts
            + [
                str(ROOT / "components/control-plane") + ":/app:ro",
                str(ROOT / "tests/fixtures/runtime_authorizer.py") + ":/fixture.py:ro",
                str(ROOT / "tests/fixtures/runtime_protocol.py")
                + ":/runtime_protocol.py:ro",
            ],
            "environment": {
                "PYTHONPATH": "/app",
                "PYTHONDONTWRITEBYTECODE": "1",
                "DJANGO_SECRET_KEY_FILE": "/trial/signing",
                "FIRST_ADMIN_PASSWORD_FILE": "/trial/first-admin",
                "KEEPLANE_SQLITE_PATH": "/state/keeplane.db",
                "PUBLIC_ORIGIN": "http://127.0.0.1:8090",
                "GATEWAY_URL": "http://127.0.0.1:4000",
                "GATEWAY_ADMIN_KEY_FILE": "/trial/admin",
                "GATEWAY_RUNTIME_KEY_FILE": "/trial/admin",
                "RUNTIME_AUTHORIZER_KEY_FILE": "/trial/gateway-key",
                "FIXTURE_SHARED_PROVIDER_KEY": "1",
                "FIXTURE_NATIVE_FALLBACK": "1" if fallback else "0",
                "FIXTURE_NATIVE_PROTOCOL": "1" if protocol else "0",
                "FIXTURE_PROVIDER_KEY_NAME": names[0],
                "FIXTURE_PROVIDER_NEXT_KEY_NAME": names[1],
                "PROVIDER_KEY_DIR": "/trial",
            },
        },
        "client": {
            "image": IMAGES["python_fixture"],
            "command": ["python", "-c", "import time; time.sleep(3600)"],
            "tmpfs": ["/client:mode=700"],
            "volumes": [
                str(ROOT / "tests/fixtures/runtime_client.py") + ":/client.py:ro"
            ],
        },
    }
    for service in services.values():
        service.update(
            {
                "pull_policy": "never",
                "read_only": True,
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
            }
        )
    compose = tmp_path / "compose.json"
    compose.write_text(
        json.dumps({"services": services, "networks": {"default": {"internal": True}}})
    )

    def dc(*args, **kwargs):
        return command(
            "docker", "compose", "-p", project, "-f", str(compose), *args, **kwargs
        )

    def call(action, argument=""):
        return json.loads(
            dc("exec", "-T", "fixture", "python", "/fixture.py", action, argument)
        )

    def probe(options):
        return json.loads(
            dc("exec", "-T", "client", "python", "/client.py", json.dumps(options))
        )

    try:
        dc("up", "-d")
        dc(
            "exec",
            "-T",
            "fixture",
            "python",
            "-c",
            "from pathlib import Path; import time\nfor _ in range(400):\n if Path('/state/ready').exists(): break\n time.sleep(.1)\nelse: raise RuntimeError('Disposable authorizer not ready')",
        )
        seed = dc("exec", "-T", "fixture", "cat", "/state/credential")
        values["session"] = json.loads(seed)["token"]
        dc(
            "exec",
            "-T",
            "client",
            "python",
            "-c",
            "from pathlib import Path; import sys; Path('/client/credential').write_bytes(sys.stdin.buffer.read())",
            input=seed,
        )
        yield SimpleNamespace(
            call=call,
            probe=probe,
            public_key_file=trial / names[1],
            before=call("config"),
        )
    finally:
        dc("down", "--volumes", "--remove-orphans", "--timeout", "2")
        for resource in ("container", "network"):
            assert not command(
                "docker",
                resource,
                "ls",
                "-q",
                "--filter",
                "label=com.docker.compose.project=" + project,
            ).strip()
