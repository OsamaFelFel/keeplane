"""Owned native token-exchange fixture; never attaches to a product preview."""

import hashlib
import json
import os
import secrets
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_trial(directory, *, http_transport=False):
    source = Path(os.environ["KEEPLANE_PERSONAL_DISPATCH_SOURCE"]).resolve()
    image = os.environ["KEEPLANE_OAUTH_FIXTURE_IMAGE"]
    assert (
        source / "components/control-plane/model_registry/personal_dispatch.py"
    ).is_file()
    if http_transport:
        assert (
            source / "components/control-plane/model_registry/personal_transport.py"
        ).is_file()
    project = "keeplane-personal-" + uuid.uuid4().hex[:10]
    directory.mkdir(mode=0o755)
    value = {
        "id": "personal",
        "name": "personal",
        "provider": "openAI",
        "params": {"model": "synthetic", "baseUrl": "http://127.0.0.1:18080/v1"},
    }
    digest = hashlib.sha256(
        json.dumps(
            {"value": value, "revision": 1}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    for name in ("callback-key", "admin", "first-admin", "signing"):
        path = directory / name
        path.write_text(secrets.token_urlsafe(64))
        path.chmod(0o644)  # Synthetic inputs within pytest's private parent.
    (directory / "definition.json").write_text(
        json.dumps({"value": value, "digest": digest})
    )
    exchange = {
        "host": "127.0.0.1:18081",
        "path": "/internal/runtime/provider-token" if http_transport else "/token",
        "cache": {"maxEntries": 0},
        "additionalParams": {
            "project_id": 'request.headers["x-keeplane-project-id"]',
            "model_id": '"personal"',
            "definition_fingerprint": json.dumps(digest),
        },
        "policies": {
            "backendAuth": {
                "key": {
                    "value": {"file": "/trial/callback-key"},
                    "location": {
                        "header": {
                            "name": "x-keeplane-gateway-credential",
                            "prefix": "",
                        }
                    },
                }
            }
        },
    }
    config = {
        "config": {
            "adminAddr": "127.0.0.1:15000",
            "storage": {"mode": "hybrid"},
            "database": {"url": "sqlite:///data/gateway.db"},
            "sensitiveHeaders": ["authorization", "x-keeplane-gateway-credential"],
        },
        "gateways": {"default": {"port": 4000}},
        "ui": {
            "gateways": "default",
            "policies": {
                "apiKey": {
                    "mode": "strict",
                    "keys": [
                        {
                            "keyHash": "sha256:"
                            + hashlib.sha256(
                                (directory / "admin").read_bytes()
                            ).hexdigest()
                        }
                    ],
                }
            },
        },
        "llm": {
            "models": [],
            "policies": {
                "apiKey": {
                    "mode": "strict",
                    "keys": [
                        {
                            "keyHash": "sha256:"
                            + hashlib.sha256(
                                (directory / "admin").read_bytes()
                            ).hexdigest()
                        }
                    ],
                }
            },
        },
        "binds": [
            {
                "port": 5000,
                "listeners": [
                    {
                        "protocol": "HTTP",
                        "routes": [
                            {
                                "matches": [
                                    {"path": {"exact": "/v1/chat/completions"}}
                                ],
                                "backends": [{"backend": "llm:router"}],
                            }
                        ],
                    }
                ],
            }
        ],
        "policies": [
            {
                "name": {"name": "personal-exchange", "namespace": ""},
                "target": {
                    "backend": {
                        "backend": {"name": "llm:model:personal", "namespace": ""}
                    }
                },
                "policy": {"backendAuth": {"oauthTokenExchange": exchange}},
            },
            {
                "name": {"name": "personal-strip", "namespace": ""},
                "target": {
                    "backend": {
                        "backend": {"name": "llm:model:personal", "namespace": ""}
                    }
                },
                "policy": {
                    "transformations": {
                        "request": {
                            "replace": '{"content-type": "application/json", "authorization": request.headers["authorization"]}'
                        }
                    }
                },
            },
        ],
    }
    (directory / "gateway.json").write_text(json.dumps(config))
    for path in directory.iterdir():
        path.chmod(0o644)
    images = json.loads((ROOT / "deploy/local/stack.lock.json").read_text())["images"]
    worker = ROOT / "tests/fixtures/native_personal_dispatch.py"
    services = {
        "gateway": {
            "image": images["agentgateway"],
            "command": ["-f", "/trial/gateway.json"],
            "volumes": [str(directory) + ":/trial:ro"],
            "tmpfs": ["/data:uid=65532,gid=65532,mode=700"],
        },
        "worker": {
            "image": image,
            "network_mode": "service:gateway",
            "depends_on": ["gateway"],
            "command": ["python", "/fixture.py"],
            "tmpfs": ["/state:uid=65532,gid=65532,mode=700"],
            "volumes": [
                str(directory) + ":/trial:ro",
                str(worker) + ":/fixture.py:ro",
                str(source / "components/control-plane") + ":/app:ro",
            ],
            "environment": {
                "PYTHONPATH": "/app:/opt/oauth",
                "PYTHONDONTWRITEBYTECODE": "1",
                "DJANGO_SETTINGS_MODULE": "config.settings",
                "DJANGO_SECRET_KEY_FILE": "/trial/signing",
                "FIRST_ADMIN_PASSWORD_FILE": "/trial/first-admin",
                "KEEPLANE_SQLITE_PATH": "/state/app.db",
                "KEEPLANE_CLI_OAUTH_ENABLED": "1",
                "PUBLIC_ORIGIN": "http://127.0.0.1:8090",
            },
        },
    }
    for service in services.values():
        service.update(
            user="65532:65532",
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            pull_policy="never",
        )
    if http_transport:
        services["worker"]["environment"].update(
            {
                "KEEPLANE_PERSONAL_HTTP_TRANSPORT": "1",
                "GATEWAY_URL": "http://127.0.0.1:4000",
                "GATEWAY_ADMIN_KEY_FILE": "/trial/admin",
                "GATEWAY_RUNTIME_KEY_FILE": "/trial/admin",
                "RUNTIME_AUTHORIZER_KEY_FILE": "/trial/callback-key",
                "PROVIDER_KEY_DIR": "/state/keys",
            }
        )
    compose = directory / "compose.json"
    compose.write_text(
        json.dumps({"services": services, "networks": {"default": {"internal": True}}})
    )
    dc = ["docker", "compose", "-p", project, "-f", str(compose)]

    def command(args, *, timeout=30, required=True, data=None):
        completed = subprocess.run(
            args, input=data, capture_output=True, timeout=timeout, check=False
        )
        if required and completed.returncode:
            raise RuntimeError("Owned personal-key fixture command failed")
        return completed.stdout

    backend = source / "components/control-plane"
    manifest = {
        str(path.relative_to(backend)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(backend.rglob("*.py"))
    }
    report = {
        "http_transport": http_transport,
        "backend_manifest_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode()
        ).hexdigest(),
        "worker_sha256": hashlib.sha256(worker.read_bytes()).hexdigest(),
        "optional_lock_sha256": hashlib.sha256(
            (backend / "requirements-cli-auth.txt").read_bytes()
        ).hexdigest(),
    }
    try:
        # Resolve the caller's cached optional image before creating resources.
        report["app_image"] = (
            command(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
            .decode()
            .strip()
        )
        report["gateway_image"] = images["agentgateway"]
        command(dc + ["up", "-d"], timeout=45)
        command(
            dc
            + [
                "exec",
                "-T",
                "worker",
                "python",
                "-c",
                "import time\nfrom pathlib import Path\nfor _ in range(900):\n if Path('/state/done').exists():break\n time.sleep(.1)\nelse:raise RuntimeError('Owned personal-key fixture timed out')",
            ],
            timeout=95,
        )
        report.update(
            json.loads(
                command(dc + ["exec", "-T", "worker", "cat", "/state/result.json"])
            )
        )
        logs = command(dc + ["logs", "--no-color"], required=False)
        report.update(
            json.loads(
                command(
                    dc + ["exec", "-T", "worker", "python", "/fixture.py", "audit"],
                    data=logs,
                )
            )
        )
        log_file = directory / "logs-private.txt"
        log_file.write_bytes(logs)
        log_file.chmod(0o600)
    finally:
        command(
            dc + ["down", "--volumes", "--remove-orphans", "--timeout", "2"], timeout=40
        )
        report["cleaned"] = all(
            not command(
                [
                    "docker",
                    kind,
                    "ls",
                    "-q",
                    "--filter",
                    "label=com.docker.compose.project=" + project,
                ]
            ).strip()
            for kind in ("container", "network")
        )
        (directory / "result.json").write_text(json.dumps(report, indent=2))
    return report
