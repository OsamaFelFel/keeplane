"""Native extAuth uses real Django policy without forwarding prompts to it."""

import hashlib
import json
import os
import secrets
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGES = json.loads((ROOT / "deploy/local/stack.lock.json").read_text())["images"]


def external_authorization(model_expression):
    return {
        "host": "127.0.0.1:8090",
        "failureMode": "deny",
        "includeRequestHeaders": ["authorization"],
        "policies": {
            "backendAuth": {
                "key": {
                    "value": {"file": "/trial/gateway-key"},
                    "location": {
                        "header": {
                            "name": "x-keeplane-gateway-credential",
                            "prefix": "",
                        }
                    },
                }
            }
        },
        "protocol": {
            "http": {
                "path": '"/internal/runtime/authorize"',
                "addRequestHeaders": {
                    "content-type": '"application/json"',
                    ":method": '"POST"',
                },
                "body": '{"project_id": request.headers["x-keeplane-project-id"], "model_id": '
                + model_expression
                + "}",
            }
        },
    }


def model_definition(name):
    return {
        "id": name,
        "name": name,
        "provider": {"custom": {"formats": [{"type": "completions"}]}},
        "params": {"model": "mock-" + name, "baseUrl": "http://127.0.0.1:18080/v1"},
        "requestHeaders": {
            "remove": [
                "authorization",
                "x-keeplane-gateway-credential",
                "x-keeplane-project-id",
            ]
        },
    }


def gateway_config(existing, admin):
    models = [model_definition("customer-owned")] if existing else []
    protected = {
        "matches": [{"path": {"exact": "/v1/chat/completions"}}],
        "backends": [{"host": "127.0.0.1:4000"}],
        "policies": {"extAuthz": external_authorization("json(request.body).model")},
    }
    rewrite = json.loads(json.dumps(protected))
    rewrite["matches"][0]["headers"] = [
        {"name": "x-fixture-rewrite", "value": {"exact": "public"}}
    ]
    rewrite["policies"]["transformations"] = {
        "request": {"body": 'json(request.body).merge({"model": "public"})'}
    }
    return {
        "config": {
            "adminAddr": "127.0.0.1:15000",
            "statsAddr": "127.0.0.1:15020",
            "readinessAddr": "127.0.0.1:15021",
            "storage": {"mode": "hybrid"},
            "database": {"url": "sqlite:///data/gateway.db"},
            "sensitiveHeaders": ["authorization", "x-keeplane-gateway-credential"],
        },
        "gateways": {"default": {"port": 4000, "bindAddress": "127.0.0.1"}},
        "ui": {
            "gateways": "default",
            "policies": {
                "apiKey": {
                    "mode": "strict",
                    "keys": [
                        {
                            "keyHash": "sha256:"
                            + hashlib.sha256(admin.encode()).hexdigest()
                        }
                    ],
                }
            },
        },
        "llm": {"models": models},
        "binds": [
            {
                "port": 5000,
                "listeners": [
                    {
                        "name": "protected-chat",
                        "protocol": "HTTP",
                        "routes": [rewrite, protected],
                    }
                ],
            }
        ],
        "policies": [
            {
                "name": {"name": "selected-" + name, "namespace": ""},
                "target": {
                    "backend": {
                        "backend": {"name": "llm:model:" + name, "namespace": ""}
                    }
                },
                "policy": {"extAuthz": external_authorization(json.dumps(name))},
            }
            for name in ("private", "public", "outside")
        ],
    }


@pytest.mark.live
@pytest.mark.infrastructure
@pytest.mark.parametrize("existing", [False, True], ids=["managed", "existing"])
@pytest.mark.parametrize("shared", [False, True], ids=["no-key", "shared-key"])
def test_native_metadata_and_selected_model_gate(
    tmp_path, report_file, existing, shared
):
    project = "keeplane-auth-" + uuid.uuid4().hex[:10]
    trial_dir = tmp_path / "trial"
    trial_dir.mkdir(mode=0o755)
    admin = secrets.token_urlsafe(32)
    provider_key = secrets.token_urlsafe(32)
    initial_key_name = "key-" + uuid.uuid4().hex
    revision_key_name = "key-" + uuid.uuid4().hex
    for name, value in (
        ("admin", admin),
        ("gateway-key", secrets.token_urlsafe(32)),
        ("first-admin", secrets.token_urlsafe(32)),
        ("signing", secrets.token_urlsafe(64)),
        (initial_key_name, provider_key),
        ("provider-expected", provider_key),
    ):
        (trial_dir / name).write_text(value)
        (trial_dir / name).chmod(
            0o644
        )  # Synthetic files inside pytest's private parent.
    (trial_dir / "gateway.yaml").write_text(json.dumps(gateway_config(existing, admin)))

    def command(*args, **kwargs):
        result = subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=60, **kwargs
        )
        assert result.returncode == 0, (
            "Disposable fixture command failed: " + result.stderr
        )
        return result.stdout

    app_image = command(
        "docker",
        "image",
        "inspect",
        os.environ.get("KEEPLANE_RUNTIME_FIXTURE_IMAGE", IMAGES["app_docker"]),
        "--format",
        "{{.Id}}",
    ).strip()
    mounts = [str(trial_dir) + ":/trial:ro"]
    services = {
        "gateway": {
            "image": IMAGES["agentgateway"],
            "command": ["-f", "/trial/gateway.yaml"],
            "volumes": mounts,
            "read_only": True,
            "tmpfs": ["/data:uid=65532,gid=65532,mode=700"],
        },
        "fixture": {
            "image": app_image,
            "command": ["python", "/fixture.py", "serve"],
            "network_mode": "service:gateway",
            "depends_on": ["gateway"],
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
                "KEEPLANE_SQLITE_PATH": "/state/keeplane.db",
                "PUBLIC_ORIGIN": "http://127.0.0.1:8090",
                "GATEWAY_URL": "http://127.0.0.1:4000",
                "GATEWAY_ADMIN_KEY_FILE": "/trial/admin",
                "GATEWAY_RUNTIME_KEY_FILE": "/trial/admin",
                "RUNTIME_AUTHORIZER_KEY_FILE": "/trial/gateway-key",
                "FIXTURE_SHARED_PROVIDER_KEY": "1" if shared else "0",
                "FIXTURE_PROVIDER_KEY_NAME": initial_key_name,
                "FIXTURE_PROVIDER_NEXT_KEY_NAME": revision_key_name,
                "PROVIDER_KEY_DIR": "/trial",
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
        },
    }
    for service in services.values():
        service.update(
            {
                "cap_drop": ["ALL"],
                "security_opt": ["no-new-privileges:true"],
                "pull_policy": "never",
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

    def fixture(action, options=None):
        if action == "probe":
            return json.loads(
                dc(
                    "exec",
                    "-T",
                    "client",
                    "python",
                    "/client.py",
                    json.dumps(options or {}),
                )
            )
        return json.loads(
            dc(
                "exec",
                "-T",
                "fixture",
                "python",
                "/fixture.py",
                action,
                json.dumps(options or {}),
            )
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
        # Pass only the developer's test session through stdin, never argv or logs.
        dc(
            "exec",
            "-T",
            "client",
            "python",
            "-c",
            "from pathlib import Path; import sys; Path('/client/credential').write_bytes(sys.stdin.buffer.read())",
            input=dc("exec", "-T", "fixture", "cat", "/state/credential"),
        )
        before = fixture("config")
        assert before["existing_preserved"] and before["existing_listed"] is existing
        assert fixture("probe") == 200
        allowed = fixture("summary")
        assert allowed["calls"] == ["mock-private"]
        assert allowed["credential_headers"] == [
            {
                "Authorization": shared,
                "X-Keeplane-Gateway-Credential": False,
                "X-Keeplane-Project-ID": False,
            }
        ]
        assert allowed["provider_key_used"] == [shared]
        assert allowed["developer_key_forwarded"] == [False]
        assert [row["model_id"] for row in allowed["decisions"]] == [
            "private",
            "private",
        ]
        fixture("reset")
        assert fixture("probe", {"headers": {"x-fixture-rewrite": "public"}}) == 403
        rewritten = fixture("summary")
        assert not rewritten["calls"]
        assert [row["model_id"] for row in rewritten["decisions"]] == [
            "private",
            "public",
        ]
        for model in ("public", "outside", "customer-owned"):
            assert fixture("probe", {"body": {"model": model, "messages": []}}) == 403
        assert (
            fixture("probe", {"headers": {"X-Keeplane-Project-ID": str(uuid.uuid4())}})
            == 403
        )
        assert fixture("probe", {"headers": {"Authorization": "Bearer invalid"}}) == 401
        assert fixture("probe", {"path": "/api/config"}) == 404
        assert (
            fixture("config") == before
        )  # Pre-existing native definitions stay intact.
        isolation = json.loads(
            dc(
                "exec",
                "-T",
                "client",
                "python",
                "-c",
                "import json, urllib.request, urllib.error\nresult={}\nfor port in (4000,15000,15020,15021,8090,18080,5000):\n try:\n  with urllib.request.urlopen('http://gateway:'+str(port)+'/api/config',timeout=1) as r: result[str(port)]=r.status\n except urllib.error.HTTPError as e: result[str(port)]=e.code\n except OSError: result[str(port)]=0\nprint(json.dumps(result))",
            )
        )
        assert all(
            isolation[str(port)] == 0
            for port in (4000, 15000, 15020, 15021, 8090, 18080)
        )
        assert isolation["5000"] == 404
        if shared:
            replacement = secrets.token_urlsafe(32)
            key_file = trial_dir / initial_key_name
            expected_file = trial_dir / "provider-expected"
            initial_revision = fixture("resource_revision")
            key_file.write_text(replacement)
            expected_file.write_text(replacement)
            diagnostic = {"existing": existing, "in_place": [], "api_revision": []}

            def observe(stage):
                fixture("reset")
                for _ in range(3):
                    status = fixture("probe")
                    observed = fixture("summary")
                    matched = bool(
                        observed["provider_key_used"]
                        and observed["provider_key_used"][-1]
                    )
                    stage.append({"status": status, "new_key_received": matched})
                    if matched:
                        break
                    time.sleep(0.2)

            observe(diagnostic["in_place"])
            diagnostic["in_place_revision_unchanged"] = (
                fixture("resource_revision") == initial_revision
            )
            # Use a different value and file so readback cannot pass on the old route.
            revision_key = secrets.token_urlsafe(32)
            active_key_file = trial_dir / revision_key_name
            active_key_file.write_text(revision_key)
            expected_file.write_text(revision_key)
            diagnostic["readback"] = fixture("publish_shared")
            assert diagnostic["readback"]["after"] > diagnostic["readback"]["before"]
            assert diagnostic["readback"]["file_reference_matches"]
            observe(diagnostic["api_revision"])
            report_file.write_text(json.dumps(diagnostic, indent=2) + "\n")
            fixture("reset")
            # Deletion follows the rotation diagnostic, never confounding it.
            active_key_file.unlink()
            assert fixture("probe") in (403, 503)
            assert not fixture("summary")["calls"]
            active_key_file.write_text(revision_key)
            active_key_file.chmod(0)
            assert fixture("probe") in (403, 503)
            assert not fixture("summary")["calls"]
            active_key_file.chmod(0o644)
            assert fixture("config")["existing_preserved"]
        fixture("withdraw")
        assert fixture("probe") == 403
        fixture("revoke")
        assert fixture("probe") == 401
        current = fixture("summary")
        assert not current["calls"]
        assert all(
            row["keys"] == ["model_id", "project_id"] for row in current["decisions"]
        )
        dc("kill", "-s", "SIGUSR1", "fixture")
        assert fixture("probe") in (403, 503)
        assert not fixture("summary")["calls"]
    except Exception:
        diagnostics = dc("logs", "--no-color", "--tail", "30", "gateway", "fixture")
        for path in trial_dir.iterdir():
            if path.name != "gateway.yaml":
                diagnostics = diagnostics.replace(
                    path.read_text().strip(), "[redacted]"
                )
        print(diagnostics)
        raise
    finally:
        dc("down", "-v", "--remove-orphans")
        assert not command(
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=com.docker.compose.project=" + project,
        ).strip()
        assert not command(
            "docker",
            "network",
            "ls",
            "-q",
            "--filter",
            "label=com.docker.compose.project=" + project,
        ).strip()
