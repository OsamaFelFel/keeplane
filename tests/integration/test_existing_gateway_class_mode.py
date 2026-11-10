"""Spec 005 ST18 data-class mode on a customer-run gateway, on SQLite and PostgreSQL.

Cases: tests/integration/existing-gateway-class-mode-cases.md (XCM-01 to XCM-08).
A real pinned agentgateway, configured as a customer would run it, calls
Keeplane's shared route and final checks; the admin turns data classes off and
on through Keeplane's admin API in separate processes.
"""

import hashlib
import json
import os
import secrets
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGES = json.loads((ROOT / "deploy/local/stack.lock.json").read_text())["images"]
# The PostgreSQL app image has the SQLite driver too, so both arms use it.
APP_IMAGE = os.environ.get(
    "KEEPLANE_RUNTIME_POSTGRES_IMAGE", "keeplane-preview:postgres-local"
)
STARTERS = ["Public", "Internal", "Confidential"]
# Marks developer traffic: the gateway's developer route sets it, so the final
# check on each model knows a developer request from Keeplane's setup probe.
DEVELOPER = 'request.headers["x-keeplane-developer-route"] == "1"'


def check(path, model_expression, *, final=False):
    """One Keeplane check as the customer wires it into agentgateway."""
    body = (
        '{"project_id": request.headers["x-keeplane-project-id"], "model_id": '
        + model_expression
        + "}"
    )
    http = {
        "path": json.dumps(path),
        "addRequestHeaders": {
            "content-type": '"application/json"',
            ":method": '"POST"',
        },
        "body": body,
    }
    if final:
        # Keeplane's own setup probe reaches each model through the gateway's
        # model port with the gateway's runtime key and no project. It has no
        # developer session, so the final check would refuse it; it goes to
        # the fixture's probe check instead.
        http["path"] = (
            f'"x-keeplane-developer-route" in request.headers && {DEVELOPER} '
            f'? {json.dumps(path)} : "/internal/fixture/setup-probe"'
        )
        http["body"] = (
            f'"x-keeplane-developer-route" in request.headers && {DEVELOPER} '
            f'? {body} : "{{}}"'
        )
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
        "protocol": {"http": http},
    }


def gateway_config(admin):
    developer = {
        "matches": [{"path": {"exact": "/v1/chat/completions"}}],
        "backends": [{"host": "127.0.0.1:4000"}],
        "policies": {
            "extAuthz": check(
                "/internal/runtime/authorize", "json(request.body).model"
            ),
        },
    }
    # A request the route check passes for one model, then changed to
    # reviewer before the gateway picks the model: only the final check sees it.
    rewrite = json.loads(json.dumps(developer))
    rewrite["matches"][0]["headers"] = [
        {"name": "x-fixture-rewrite", "value": {"exact": "reviewer"}}
    ]
    rewrite["policies"]["transformations"] = {
        "request": {"body": 'json(request.body).merge({"model": "reviewer"})'}
    }
    customer_owned = {
        "id": "customer-owned",
        "name": "customer-owned",
        "provider": {"custom": {"formats": [{"type": "completions"}]}},
        "params": {
            "model": "mock-customer-owned",
            "baseUrl": "http://127.0.0.1:18080/v1",
        },
        "requestHeaders": {
            "remove": [
                "authorization",
                "x-keeplane-gateway-credential",
                "x-keeplane-project-id",
                "x-keeplane-developer-route",
            ]
        },
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
        # Added by the customer outside Keeplane; Keeplane never sets it up.
        "llm": {"models": [customer_owned]},
        "binds": [
            {
                "port": 5000,
                "listeners": [
                    {
                        "name": "developer-chat",
                        "protocol": "HTTP",
                        # Set before the route check, over any client value.
                        "policies": {
                            "transformations": {
                                "request": {
                                    "set": {"x-keeplane-developer-route": '"1"'}
                                }
                            }
                        },
                        "routes": [rewrite, developer],
                    }
                ],
            }
        ],
        "policies": [
            {
                "name": {"name": "final-" + name, "namespace": ""},
                "target": {
                    "backend": {
                        "backend": {"name": "llm:model:" + name, "namespace": ""}
                    }
                },
                "policy": {
                    "extAuthz": check(
                        "/internal/runtime/authorize/selected",
                        json.dumps(name),
                        final=True,
                    )
                },
            }
            for name in ("coder", "reviewer", "late-coder", "customer-owned")
        ],
    }


@pytest.fixture(params=["sqlite", "postgresql"])
def trial(request, tmp_path):
    database = request.param
    project = "keeplane-class-mode-" + uuid.uuid4().hex[:10]
    trial_dir = tmp_path / "trial"
    trial_dir.mkdir(mode=0o755)
    values = {
        "admin": secrets.token_urlsafe(32),
        "gateway-key": secrets.token_urlsafe(32),
        "first-admin": secrets.token_urlsafe(32),
        "signing": secrets.token_urlsafe(64),
        "database-password": secrets.token_urlsafe(24),
    }
    for name, value in values.items():
        (trial_dir / name).write_text(value)
        # Synthetic values inside pytest's private parent, read by other users.
        (trial_dir / name).chmod(0o644)
    (trial_dir / "gateway.yaml").write_text(json.dumps(gateway_config(values["admin"])))

    def command(*args, **kwargs):
        result = subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=180, **kwargs
        )
        detail = result.stderr
        for value in values.values():
            detail = detail.replace(value, "[redacted]")
        assert result.returncode == 0, "Disposable fixture failed: " + detail[-2000:]
        return result.stdout

    image = command("docker", "image", "inspect", APP_IMAGE, "--format", "{{.Id}}")
    mounts = [str(trial_dir) + ":/trial:ro"]
    environment = {
        "PYTHONPATH": "/app",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GATEWAY_MODE": "existing",
        "DJANGO_SECRET_KEY_FILE": "/trial/signing",
        "FIRST_ADMIN_PASSWORD_FILE": "/trial/first-admin",
        "PUBLIC_ORIGIN": "http://127.0.0.1:8090",
        "GATEWAY_URL": "http://127.0.0.1:4000",
        "GATEWAY_ADMIN_KEY_FILE": "/trial/admin",
        "GATEWAY_RUNTIME_KEY_FILE": "/trial/admin",
        "RUNTIME_AUTHORIZER_KEY_FILE": "/trial/gateway-key",
    }
    services = {
        "gateway": {
            "image": IMAGES["agentgateway"],
            "command": ["-f", "/trial/gateway.yaml"],
            "volumes": mounts,
            "read_only": True,
            "tmpfs": ["/data:uid=65532,gid=65532,mode=700"],
            # The disposable network is IPv4 only.
            "environment": {"IPV6_ENABLED": "false"},
        },
        "fixture": {
            "image": image.strip(),
            "command": ["python", "/fixture.py", "serve"],
            "network_mode": "service:gateway",
            "depends_on": ["gateway"],
            "read_only": True,
            "tmpfs": ["/state:uid=65532,gid=65532,mode=700"],
            "volumes": mounts
            + [
                str(ROOT / "components/control-plane") + ":/app:ro",
                str(ROOT / "tests/fixtures/class_mode_gateway.py") + ":/fixture.py:ro",
            ],
            "environment": environment,
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
    if database == "sqlite":
        environment["KEEPLANE_SQLITE_PATH"] = "/state/keeplane.sqlite3"
    else:
        # The production storage settings: the app's own database user and a
        # password file. TLS to PostgreSQL is checked by the chart and
        # deployment cases; this disposable network has no certificates.
        environment.update(
            {
                "KEEPLANE_DATABASE_HOST": "database",
                "KEEPLANE_DATABASE_NAME": "keeplane",
                "KEEPLANE_DATABASE_USER": "keeplane",
                "KEEPLANE_DATABASE_PASSWORD_FILE": "/trial/database-password",
                "KEEPLANE_DATABASE_SSLMODE": "disable",
            }
        )
        services["database"] = {
            "image": IMAGES["postgres"],
            "environment": {
                "POSTGRES_USER": "keeplane",
                "POSTGRES_DB": "keeplane",
                "POSTGRES_PASSWORD_FILE": "/trial/database-password",
            },
            "volumes": mounts,
            "tmpfs": ["/var/lib/postgresql", "/var/run/postgresql"],
            "healthcheck": {
                "test": ["CMD", "pg_isready", "-U", "keeplane", "-d", "keeplane"],
                "interval": "1s",
                "retries": 60,
            },
        }
        services["fixture"]["depends_on"] = {
            "gateway": {"condition": "service_started"},
            "database": {"condition": "service_healthy"},
        }
    for name, service in services.items():
        service.update(
            {"pull_policy": "never", "security_opt": ["no-new-privileges:true"]}
        )
        if name != "database":
            # PostgreSQL's entrypoint needs its default capabilities to start.
            service["cap_drop"] = ["ALL"]
    compose = tmp_path / "compose.json"
    compose.write_text(
        json.dumps({"services": services, "networks": {"default": {"internal": True}}})
    )

    def dc(*args, **kwargs):
        return command(
            "docker", "compose", "-p", project, "-f", str(compose), *args, **kwargs
        )

    def fixture(action, argument=None):
        args = ["exec", "-T", "fixture", "python", "/fixture.py", action]
        if argument is not None:
            args.append(json.dumps(argument))
        return json.loads(dc(*args))

    def admin(method, path, body=None):
        result = fixture("admin", {"method": method, "path": path, "body": body})
        return result["status"], result["body"]

    def ask(model, project="classed", rewrite=False, marker=None):
        """A developer request through the gateway's developer route."""
        headers = {"X-Keeplane-Project-ID": projects[project]}
        if rewrite:
            headers["x-fixture-rewrite"] = "reviewer"
        if marker is not None:
            # A developer's own value for the gateway's developer marker.
            headers["x-keeplane-developer-route"] = marker
        fixture("reset")
        status = json.loads(
            dc(
                "exec",
                "-T",
                "client",
                "python",
                "/client.py",
                json.dumps(
                    {
                        "headers": headers,
                        "body": {
                            "model": model,
                            "messages": [{"role": "user", "content": "synthetic"}],
                        },
                    }
                ),
            )
        )
        seen = fixture("summary")
        return {
            "status": status,
            "sent_to": seen["calls"],
            "checks": [
                (row["check"], row["model_id"], row["status"])
                for row in seen["decisions"]
            ],
            "keys": sorted({tuple(row["keys"]) for row in seen["decisions"]}),
            "forwarded": seen["forwarded"],
        }

    def direct(model, headers=None):
        """A developer's session sent straight to the gateway's model port."""
        fixture("reset")
        reached = json.loads(
            dc(
                "exec",
                "-T",
                "client",
                "python",
                "-c",
                "import json, urllib.request\n"
                "try:\n"
                " urllib.request.urlopen('http://gateway:4000/v1/chat/completions', b'{}', timeout=2)\n"
                " print(json.dumps(True))\n"
                "except urllib.error.HTTPError:\n"
                " print(json.dumps(True))\n"
                "except OSError:\n"
                " print(json.dumps(False))",
            )
        )
        status = fixture("direct", {"model": model, "headers": headers or {}})["status"]
        seen = fixture("summary")
        return {
            "reachable_from_client": reached,
            "status": status,
            "sent_to": seen["calls"],
            "checks": [
                (row["check"], row["model_id"], row["status"])
                for row in seen["decisions"]
            ],
            "key_only_check": seen["setup_probes"],
        }

    projects = {}
    try:
        dc("up", "-d")
        dc(
            "exec",
            "-T",
            "fixture",
            "python",
            "-c",
            "from pathlib import Path; import time\nfor _ in range(900):\n if Path('/state/ready').exists(): break\n time.sleep(.1)\nelse: raise RuntimeError('Disposable app not ready')",
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
        projects.update(fixture("projects"))
        yield type(
            "Trial",
            (),
            {
                "database": database,
                "admin": staticmethod(admin),
                "ask": staticmethod(ask),
                "fixture": staticmethod(fixture),
                "direct": staticmethod(direct),
                "projects": projects,
            },
        )
    except Exception:
        logs = dc("logs", "--no-color", "--tail", "40", "gateway", "fixture")
        for value in values.values():
            logs = logs.replace(value, "[redacted]")
        print(logs)
        raise
    finally:
        dc("down", "-v", "--remove-orphans")


def sent(model, final=True):
    """What a request the checks allow looks like: both checks, one call."""
    checks = [("route", model, 200)] + ([("final", model, 200)] if final else [])
    return {"status": 200, "sent_to": ["mock-" + model], "checks": checks}


def refused_at_route(model):
    return {"status": 403, "sent_to": [], "checks": [("route", model, 403)]}


def outcome(result):
    return {key: result[key] for key in ("status", "sent_to", "checks")}


def mode(trial, enabled):
    assert trial.admin("PUT", "/api/data-classes/mode", {"enabled": enabled})[0] == 200


def class_state(trial):
    """Classes, their approvals, project classes and model approvals, as an admin reads them."""
    status, listing = trial.admin("GET", "/api/data-classes")
    assert status == 200
    _, models = trial.admin("GET", "/api/models")
    projects = {
        key: trial.admin("GET", f"/api/projects/{project}/class")[1]
        for key, project in trial.projects.items()
    }
    return {
        "enabled": listing["enabled"],
        "classes": [
            (row["id"], row["name"], row["approved_model_ids"])
            for row in listing["classes"]
        ],
        "models": {
            row["id"]: (row["approved"], row["approved_classes"])
            for row in models["models"]
        },
        "projects": {
            key: (row["classes_enabled"], (row.get("data_class") or {}).get("name"))
            for key, row in projects.items()
        },
    }


@pytest.mark.live
@pytest.mark.infrastructure
def test_class_mode_on_off_on_through_a_customer_run_gateway(trial, report_file):
    observed = {"database": trial.database}

    # XCM-01: a new install starts off; models set up while off answer.
    fresh = class_state(trial)
    assert fresh["enabled"] is False and fresh["classes"] == []
    assert fresh["projects"] == {"classed": (False, None), "open": (False, None)}
    status, _ = trial.admin(
        "PUT",
        f"/api/projects/{trial.projects['classed']}/class",
        {"class_id": "public"},
    )
    assert status == 409
    for model in ("coder", "reviewer"):
        status, body = trial.admin(
            "POST", f"/api/models/{model}/setup", {"key_choice": "none"}
        )
        assert status == 200, body
    off = class_state(trial)["models"]
    assert off["coder"] == (True, []) and off["reviewer"] == (True, [])
    assert off["customer-owned"] == (False, [])
    assert outcome(trial.ask("coder")) == sent("coder")
    assert outcome(trial.ask("reviewer")) == sent("reviewer")
    assert outcome(trial.ask("customer-owned")) == refused_at_route("customer-owned")
    # Only the project and model reach Keeplane, never the prompt.
    assert trial.ask("coder")["keys"] == [("model_id", "project_id")]
    observed["XCM-01"] = "pass"

    # XCM-02: turning on adds the starters and approves nothing by itself.
    mode(trial, True)
    on = class_state(trial)
    assert [name for _, name, _ in on["classes"]] == STARTERS
    assert all(models == [] for _, _, models in on["classes"])
    assert on["models"]["coder"] == (True, []) and on["models"]["reviewer"] == (
        True,
        [],
    )
    ids = {name: class_id for class_id, name, _ in on["classes"]}
    status, _ = trial.admin(
        "PUT",
        f"/api/projects/{trial.projects['classed']}/class",
        {"class_id": ids["Confidential"]},
    )
    assert status == 200
    assert outcome(trial.ask("coder")) == refused_at_route("coder")
    assert outcome(trial.ask("coder", project="open")) == sent("coder")
    observed["XCM-02"] = "pass"

    # XCM-03: approvals and new or renamed classes apply at both checks.
    status, _ = trial.admin(
        "PUT",
        f"/api/data-classes/{ids['Confidential']}",
        {"name": "Confidential", "approved_model_ids": ["coder"]},
    )
    assert status == 200
    status, _ = trial.admin(
        "PUT",
        f"/api/data-classes/{ids['Internal']}",
        {"name": "Restricted", "approved_model_ids": []},
    )
    assert status == 200
    status, added = trial.admin(
        "POST",
        "/api/data-classes",
        {"name": "Partners", "approved_model_ids": ["reviewer"]},
    )
    assert status == 201
    assert outcome(trial.ask("coder")) == sent("coder")
    assert outcome(trial.ask("reviewer")) == refused_at_route("reviewer")
    # The route check passes coder; the final check sees reviewer and refuses.
    assert outcome(trial.ask("coder", rewrite=True)) == {
        "status": 403,
        "sent_to": [],
        "checks": [("route", "coder", 200), ("final", "reviewer", 403)],
    }
    configured = class_state(trial)
    assert configured["classes"] == [
        (ids["Public"], "Public", []),
        (ids["Internal"], "Restricted", []),
        (ids["Confidential"], "Confidential", ["coder"]),
        (added["id"], "Partners", ["reviewer"]),
    ]
    assert configured["projects"]["classed"] == (True, "Confidential")
    observed["XCM-03"] = "pass"

    # XCM-04: off keeps everything but applies none of it, at either check.
    mode(trial, False)
    hidden = class_state(trial)
    assert hidden["enabled"] is False and hidden["classes"] == []
    assert hidden["projects"] == {"classed": (False, None), "open": (False, None)}
    # Kept for later: the models still carry their approvals while off.
    assert hidden["models"]["coder"] == (True, ["Confidential"])
    assert hidden["models"]["reviewer"] == (True, ["Partners"])
    assert outcome(trial.ask("reviewer")) == sent("reviewer")
    assert outcome(trial.ask("coder", rewrite=True)) == {
        "status": 200,
        "sent_to": ["mock-reviewer"],
        "checks": [("route", "coder", 200), ("final", "reviewer", 200)],
    }
    status, body = trial.admin(
        "POST",
        "/api/models/late-coder/setup",
        {"key_choice": "none", "approved_classes": ["Confidential"]},
    )
    assert status == 200, body
    assert class_state(trial)["models"]["late-coder"] == (True, [])
    assert outcome(trial.ask("late-coder")) == sent("late-coder")
    assert outcome(trial.ask("customer-owned")) == refused_at_route("customer-owned")
    observed["XCM-04"] = "pass"

    # XCM-05: on again restores the same classes, approvals and project class,
    # and the model set up while off is approved for nothing.
    for cycle in ("XCM-05", "XCM-06"):
        mode(trial, True)
        again = class_state(trial)
        assert again["classes"] == configured["classes"]
        assert again["projects"] == configured["projects"]
        assert again["models"]["coder"] == (True, ["Confidential"])
        assert again["models"]["reviewer"] == (True, ["Partners"])
        assert again["models"]["late-coder"] == (True, [])
        assert outcome(trial.ask("coder")) == sent("coder")
        assert outcome(trial.ask("late-coder")) == refused_at_route("late-coder")
        assert outcome(trial.ask("late-coder", project="open")) == sent("late-coder")
        assert outcome(trial.ask("coder", rewrite=True))["status"] == 403
        assert outcome(trial.ask("reviewer"))["sent_to"] == []
        observed[cycle] = "pass"
        # XCM-06: a second off and on changes nothing either.
        mode(trial, False)

    # XCM-07: the customer's own model was never set up, so it was refused
    # in every state above and no class lists it.
    mode(trial, True)
    final = class_state(trial)
    assert final["models"]["customer-owned"] == (False, [])
    assert all("customer-owned" not in models for _, _, models in final["classes"])
    assert outcome(trial.ask("customer-owned")) == refused_at_route("customer-owned")
    assert outcome(trial.ask("customer-owned", project="open")) == refused_at_route(
        "customer-owned"
    )
    observed["XCM-07"] = "pass"

    # XCM-08: a developer can't skip the final check. The listener sets the
    # marker over any value the client sends, and the model port's check
    # for unmarked requests admits only Keeplane's runtime key.
    for marker in ("0", None, ""):
        assert outcome(trial.ask("coder", rewrite=True, marker=marker)) == {
            "status": 403,
            "sent_to": [],
            "checks": [("route", "coder", 200), ("final", "reviewer", 403)],
        }, marker
    allowed = trial.ask("coder", marker="0")
    assert outcome(allowed) == sent("coder")
    # Neither the marker nor Keeplane's credentials reach the provider.
    assert allowed["forwarded"] == [[]]
    straight = trial.direct("coder")
    assert straight == {
        "reachable_from_client": False,
        "status": 403,
        "sent_to": [],
        "checks": [],
        "key_only_check": [False],
    }
    observed["XCM-08"] = "pass"
    report_file.write_text(json.dumps(observed, indent=2) + "\n")
