"""Two disposable native paths query the same real Keeplane PostgreSQL policy."""

import json
import os
import secrets
import subprocess
import time
import uuid

import pytest

from tests.integration.test_native_runtime_authorization import (
    IMAGES,
    ROOT,
    gateway_config,
)


@pytest.mark.live
@pytest.mark.infrastructure
@pytest.mark.parametrize("existing", [False, True], ids=["managed", "existing"])
def test_native_replicas_use_current_primary_policy(tmp_path, report_file, existing):
    project = "keeplane-policy-pg-" + uuid.uuid4().hex[:10]
    trial = tmp_path / "trial"
    trial.mkdir(mode=0o755)
    key_name = "key-" + uuid.uuid4().hex
    admin, provider_key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    secret_values = {
        "admin": admin,
        "gateway-key": secrets.token_urlsafe(32),
        "first-admin": secrets.token_urlsafe(32),
        "signing": secrets.token_urlsafe(64),
        "database": secrets.token_urlsafe(32),
        key_name: provider_key,
        "provider-expected": provider_key,
    }
    for name, value in secret_values.items():
        (trial / name).write_text(value)
        (trial / name).chmod(0o644)
    (trial / "gateway.yaml").write_text(json.dumps(gateway_config(existing, admin)))

    def command(*args, **kwargs):
        result = subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=90, **kwargs
        )
        detail = result.stderr
        for value in secret_values.values():
            detail = detail.replace(value, "[redacted]")
        assert result.returncode == 0, "Disposable fixture failed: " + detail
        return result.stdout

    app_image = command(
        "docker",
        "image",
        "inspect",
        os.environ.get(
            "KEEPLANE_RUNTIME_POSTGRES_FIXTURE_IMAGE", "keeplane-preview:postgres-local"
        ),
        "--format",
        "{{.Id}}",
    ).strip()
    mounts = [str(trial) + ":/trial:ro"]
    services = {
        "database": {
            "image": IMAGES["postgres"],
            "environment": {
                "POSTGRES_USER": "keeplane",
                "POSTGRES_DB": "keeplane",
                "POSTGRES_PASSWORD_FILE": "/trial/database",
            },
            "volumes": mounts,
            "tmpfs": ["/var/lib/postgresql/data"],
            "networks": ["policy"],
            "healthcheck": {
                "test": ["CMD", "pg_isready", "-U", "keeplane", "-d", "keeplane"],
                "interval": "1s",
                "timeout": "3s",
                "retries": 40,
            },
        },
        "client": {
            "image": IMAGES["python_fixture"],
            "command": ["python", "-c", "import time; time.sleep(3600)"],
            "read_only": True,
            "tmpfs": ["/client:mode=700"],
            "volumes": [
                str(ROOT / "tests/fixtures/runtime_client.py") + ":/client.py:ro"
            ],
            "networks": ["runtime"],
        },
    }
    for side in ("a", "b"):
        services["gateway-" + side] = {
            "image": IMAGES["agentgateway"],
            "command": ["-f", "/trial/gateway.yaml"],
            "volumes": mounts,
            "read_only": True,
            "tmpfs": ["/data:uid=65532,gid=65532,mode=700"],
            "networks": ["runtime", "policy"],
        }
        services["fixture-" + side] = {
            "image": app_image,
            "command": ["python", "/fixture.py", "serve"],
            "network_mode": "service:gateway-" + side,
            "depends_on": ["gateway-" + side],
            "read_only": True,
            "tmpfs": ["/state:uid=65532,gid=65532,mode=700"],
            "volumes": mounts
            + [
                str(ROOT / "components/control-plane") + ":/app:ro",
                str(ROOT / "tests/fixtures/runtime_authorizer.py") + ":/fixture.py:ro",
            ],
            "environment": {
                "PYTHONPATH": "/app",
                "PYTHONDONTWRITEBYTECODE": "1",
                "DJANGO_SECRET_KEY_FILE": "/trial/signing",
                "FIRST_ADMIN_PASSWORD_FILE": "/trial/first-admin",
                "KEEPLANE_DATABASE_HOST": "database",
                "KEEPLANE_DATABASE_NAME": "keeplane",
                "KEEPLANE_DATABASE_USER": "keeplane",
                "KEEPLANE_DATABASE_PASSWORD_FILE": "/trial/database",
                "KEEPLANE_DATABASE_SSLMODE": "disable",
                "PUBLIC_ORIGIN": "http://127.0.0.1:8090",
                "GATEWAY_URL": "http://127.0.0.1:4000",
                "GATEWAY_ADMIN_KEY_FILE": "/trial/admin",
                "GATEWAY_RUNTIME_KEY_FILE": "/trial/admin",
                "RUNTIME_AUTHORIZER_KEY_FILE": "/trial/gateway-key",
                "FIXTURE_SHARED_PROVIDER_KEY": "1",
                "FIXTURE_REUSE_NATIVE_DEFINITIONS": "1",
                "FIXTURE_PROVIDER_KEY_NAME": key_name,
                "FIXTURE_SESSION_FILE": "/trial/seed-session",
                "PROVIDER_KEY_DIR": "/trial",
            },
        }
    for name, service in services.items():
        service["pull_policy"] = "never"
        service["security_opt"] = ["no-new-privileges:true"]
        if name != "database":
            service["cap_drop"] = ["ALL"]
    compose = tmp_path / "compose.json"
    compose.write_text(
        json.dumps(
            {
                "services": services,
                "networks": {
                    "runtime": {"internal": True},
                    "policy": {"internal": True},
                },
            }
        )
    )

    def dc(*args, **kwargs):
        return command(
            "docker", "compose", "-p", project, "-f", str(compose), *args, **kwargs
        )

    def fixture(side, action, argument=""):
        return json.loads(
            dc(
                "exec",
                "-T",
                "fixture-" + side,
                "python",
                "/fixture.py",
                action,
                argument,
            )
        )

    def probe(side, options=None):
        return json.loads(
            dc(
                "exec",
                "-T",
                "-e",
                "FIXTURE_GATEWAY_HOST=gateway-" + side,
                "client",
                "python",
                "/client.py",
                json.dumps(options or {}),
            )
        )

    def ready(side):
        dc(
            "exec",
            "-T",
            "fixture-" + side,
            "python",
            "-c",
            "from pathlib import Path; import time\nfor _ in range(400):\n if Path('/state/ready').exists(): break\n time.sleep(.1)\nelse: raise RuntimeError('Disposable authorizer not ready')",
        )

    def reset():
        for side in ("a", "b"):
            fixture(side, "reset")

    def denied_both(expected):
        reset()
        for side in ("a", "b"):
            assert probe(side) in expected
            assert not fixture(side, "summary")["calls"]

    recovery = {}

    def recover(label):
        statuses = recovery[label] = []
        for _ in range(8):
            statuses.append(probe("a"))
            if statuses[-1] == 200:
                return
            time.sleep(0.2)
        pytest.fail("Protected path did not recover at its stable address")

    try:
        dc("up", "-d", "--wait", "database")
        dc("up", "-d", "gateway-a", "fixture-a", "client")
        ready("a")
        seed = dc("exec", "-T", "fixture-a", "cat", "/state/credential")
        secret_values["session"] = json.loads(seed)["token"]
        (trial / "seed-session").write_text(seed)
        (trial / "seed-session").chmod(0o644)
        dc(
            "exec",
            "-T",
            "client",
            "python",
            "-c",
            "from pathlib import Path; import sys; Path('/client/credential').write_bytes(sys.stdin.buffer.read())",
            input=seed,
        )
        dc("up", "-d", "gateway-b", "fixture-b")
        ready("b")
        before = {side: fixture(side, "config") for side in ("a", "b")}
        revisions = {side: fixture(side, "resource_revision") for side in ("a", "b")}
        for side in ("a", "b"):
            assert fixture(side, "database_state") == {
                "vendor": "postgresql",
                "standby": False,
            }
            assert (
                before[side]["existing_preserved"]
                and before[side]["existing_listed"] is existing
            )
            assert probe(side) == 200
            allowed = fixture(side, "summary")
            assert allowed["calls"] == ["mock-private"]
            assert allowed["provider_key_used"] == [True]
            assert allowed["developer_key_forwarded"] == [False]
            assert allowed["credential_headers"] == [
                {
                    "Authorization": True,
                    "X-Keeplane-Gateway-Credential": False,
                    "X-Keeplane-Project-ID": False,
                }
            ]
        reset()
        for side in ("a", "b"):
            assert probe(side, {"headers": {"x-fixture-rewrite": "public"}}) == 403
            denied = fixture(side, "summary")
            assert not denied["calls"]
            assert [row["model_id"] for row in denied["decisions"]] == [
                "private",
                "public",
            ]
        # Losing A's policy network preserves its reachable protected listener.
        reset()
        container = dc("ps", "-q", "gateway-a").strip()
        command("docker", "network", "disconnect", project + "_policy", container)
        assert probe("a") in (403, 503)
        assert not fixture("a", "summary")["calls"]
        assert probe("b") == 200
        fixture("b", "withdraw")
        reset()
        assert probe("a") in (403, 503)
        assert probe("b") == 403
        assert all(not fixture(side, "summary")["calls"] for side in ("a", "b"))
        command("docker", "network", "connect", project + "_policy", container)
        assert fixture("a", "database_state")["standby"] is False
        assert probe("a") == 403
        assert not fixture("a", "summary")["calls"]
        fixture("b", "restore_approval")
        recover("database_link")
        assert probe("b") == 200
        reset()
        # Stop only authorization; a live provider makes fail-open observable.
        dc("kill", "-s", "SIGUSR1", "fixture-a")
        assert probe("a") in (403, 503)
        assert not fixture("a", "summary")["calls"]
        assert probe("b") == 200
        fixture("b", "set_classes", "disabled")
        dc("up", "-d", "--force-recreate", "--no-deps", "fixture-a")
        ready("a")
        recover("authorizer_replacement")
        assert all(fixture(side, "classes_enabled") is False for side in ("a", "b"))
        fixture("b", "set_classes", "enabled")
        assert {
            side: fixture(side, "resource_revision") for side in ("a", "b")
        } == revisions
        fixture("a", "set_class", "public")
        denied_both({403})
        fixture("a", "set_class", "confidential")
        assert all(probe(side) == 200 for side in ("a", "b"))
        fixture("a", "withdraw")
        denied_both({403})
        fixture("a", "restore_approval")
        assert all(probe(side) == 200 for side in ("a", "b"))
        (trial / key_name).unlink()
        denied_both({403, 503})
        (trial / key_name).write_text(provider_key)
        (trial / key_name).chmod(0o644)
        assert all(probe(side) == 200 for side in ("a", "b"))
        fixture("a", "revoke")
        denied_both({401})
        for side in ("a", "b"):
            assert fixture(side, "config") == before[side]
            isolation = json.loads(
                dc(
                    "exec",
                    "-T",
                    "client",
                    "python",
                    "-c",
                    "import json,socket\nr={}\nfor p in (4000,15000,15020,15021,8090,18080):\n s=socket.socket();s.settimeout(.5)\n r[p]=s.connect_ex(('gateway-"
                    + side
                    + "',p))==0;s.close()\nprint(json.dumps(r))",
                )
            )
            assert not any(isolation.values())
        report_file.write_text(
            json.dumps(
                {
                    "existing": existing,
                    "recovery_statuses": recovery,
                    "shared_primary_withdrawal": True,
                    "failed_copy_no_provider_contact": True,
                },
                indent=2,
            )
            + "\n"
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
