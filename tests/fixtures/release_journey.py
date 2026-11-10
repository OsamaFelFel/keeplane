"""Disposable PostgreSQL installs for the release journey check (task 009-15).

For tests/e2e/developer-journey-release-cases.md; never use for deployment.
``ReleaseInstall`` writes and runs its own Compose project, on loopback ports
the system picks, so it never touches the local preview on port 3000 or any
other Compose project. Both installs have:

- ``database``: PostgreSQL. The app copies use its owner role; the managed
  install's model enroller has a read-only role of its own;
- ``app-1`` and ``app-2``: two copies of the PostgreSQL app image with CLI
  sign-in, served by gunicorn as in a release, after ``app-setup`` has
  migrated and registered the CLI clients. They share one signing secret;
- ``app``: one address in front of the two copies (this file's ``front``
  action). It sends each request to the next copy in turn and counts what
  each copy answered, so a run shows that both did the work;
- ``cloud-provider``: the preview's HTTPS OpenAI fixture, with its own test
  certificate, and ``model``: a mock local model nobody sets up in Keeplane.

The gateway depends on the mode:

- ``existing``: a pinned agentgateway the customer runs, set up as the gateway
  guide says: the developer listener sets the marker, the route check is on
  the developer route, each model backend sends marked requests to the final
  check and unmarked ones (Keeplane's own setup request) to the key-only
  check, and nothing of Keeplane's reaches a provider. The customer's gateway
  holds the cloud provider key; Keeplane holds none. Each model Keeplane will
  set up is named up front, as the guide asks a customer to do.
- ``managed``: the gateway, runtime installer and model enroller of the
  Docker preview's runtime profile (deploy/local/runtime.yaml), with the
  shared provider key Keeplane keeps.
"""

import hashlib
import importlib.util
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

# In a container this file is /fixture.py, which has no repo around it.
ROOT = (
    Path(__file__).resolve().parents[min(2, len(Path(__file__).resolve().parents) - 1)]
)
MODES = ("existing", "managed")
COPIES = ("app-1", "app-2")
# A model the customer added to its own gateway; nobody sets it up in Keeplane.
CUSTOMER_MODEL = "customer-model"
# Never one of Keeplane's headers at a provider.
FORWARD_NEVER = [
    "authorization",
    "x-keeplane-gateway-credential",
    "x-keeplane-project-id",
    "x-keeplane-developer-route",
]
MARKED = (
    '"x-keeplane-developer-route" in request.headers'
    ' && request.headers["x-keeplane-developer-route"] == "1"'
)
CHECK_CREDENTIAL = {
    "backendAuth": {
        "key": {
            "value": {"file": "/trial/gateway-credential"},
            "location": {
                "header": {"name": "x-keeplane-gateway-credential", "prefix": ""}
            },
        }
    }
}


def free_port(taken=()):
    while True:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            found = sock.getsockname()[1]
        if found not in taken:
            return found


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(path, body):
    """One of Keeplane's checks, as the customer wires it into agentgateway."""
    return {
        "host": "app:3000",
        "failureMode": "deny",
        "includeRequestHeaders": ["authorization"],
        "policies": CHECK_CREDENTIAL,
        "protocol": {
            "http": {
                "path": path,
                "addRequestHeaders": {
                    "content-type": '"application/json"',
                    ":method": '"POST"',
                },
                "body": body,
            }
        },
    }


def model_policies(name, provider_key=False):
    """The policies the customer puts on one model's backend."""
    target = {"backend": {"backend": {"name": "llm:model:" + name, "namespace": ""}}}
    developer = (
        '{"project_id": request.headers["x-keeplane-project-id"], "model_id": '
        + json.dumps(name)
        + "}"
    )
    policies = [
        {
            "name": {"name": "final-" + name, "namespace": ""},
            "target": target,
            "policy": {
                # Marked: the final check. Unmarked: the key-only check.
                "extAuthz": check(
                    f'{MARKED} ? "/internal/runtime/authorize/selected"'
                    ' : "/internal/runtime/authorize/runtime-key"',
                    f'{MARKED} ? {developer} : "{{}}"',
                )
            },
        }
    ]
    outbound = '{"content-type": "application/json"'
    if provider_key:
        # The customer's own provider key, which Keeplane never holds.
        policies.append(
            {
                "name": {"name": "key-" + name, "namespace": ""},
                "target": json.loads(json.dumps(target)),
                "policy": {
                    "backendAuth": {
                        "key": {"value": {"file": "/trial/cloud-provider-key"}}
                    }
                },
            }
        )
        outbound += ', "authorization": request.headers["authorization"]'
    # Backend transformations run after the checks and the key: only the
    # provider's own headers go on.
    policies.append(
        {
            "name": {"name": "strip-" + name, "namespace": ""},
            "target": json.loads(json.dumps(target)),
            "policy": {"transformations": {"request": {"replace": outbound + "}"}}},
        }
    )
    return policies


def customer_gateway(admin_key, local_models, cloud_models):
    """The customer's agentgateway, following docs/guide/gateway-configuration.md."""
    if str(ROOT / "components/control-plane") not in sys.path:
        sys.path.insert(0, str(ROOT / "components/control-plane"))
    from integrations.gateway.runtime_config import outage_retry

    route_check = check(
        '"/internal/runtime/authorize"',
        '{"project_id": request.headers["x-keeplane-project-id"], '
        '"model_id": json(request.body).model}',
    )
    policies = []
    for name in (CUSTOMER_MODEL, *local_models):
        policies += model_policies(name)
    for name in cloud_models:
        policies += model_policies(name, provider_key=True)
    return {
        "config": {
            "adminAddr": "127.0.0.1:15000",
            "statsAddr": "127.0.0.1:15020",
            "readinessAddr": "127.0.0.1:15021",
            "storage": {"mode": "hybrid"},
            "database": {"url": "sqlite:///data/gateway.db"},
            "sensitiveHeaders": ["authorization", "x-keeplane-gateway-credential"],
        },
        # gateway.url: Keeplane's management calls and setup requests only.
        # No port is published, so developers can't reach it.
        "gateways": {"default": {"port": 4000, "bindAddress": "0.0.0.0"}},
        "ui": {
            "gateways": "default",
            "policies": {
                "apiKey": {
                    "mode": "strict",
                    "keys": [
                        {
                            "keyHash": "sha256:"
                            + hashlib.sha256(admin_key.encode()).hexdigest()
                        }
                    ],
                }
            },
        },
        "llm": {
            "models": [
                {
                    "id": CUSTOMER_MODEL,
                    "name": CUSTOMER_MODEL,
                    "provider": {"custom": {"formats": [{"type": "completions"}]}},
                    "params": {
                        "model": "mock-local",
                        "baseUrl": "http://model:18080/v1",
                    },
                    "requestHeaders": {"remove": FORWARD_NEVER},
                }
            ]
        },
        "binds": [
            {
                "port": 5000,
                "listeners": [
                    {
                        # The developer listener, published for the CLI.
                        "name": "developer-chat",
                        "protocol": "HTTP",
                        # Before routing, over any value a developer sends.
                        "policies": {
                            "transformations": {
                                "request": {
                                    "set": {"x-keeplane-developer-route": '"1"'}
                                }
                            }
                        },
                        "routes": [
                            {
                                "matches": [
                                    {
                                        "method": "POST",
                                        "path": {"exact": "/v1/chat/completions"},
                                    }
                                ],
                                "backends": [{"host": "127.0.0.1:4000"}],
                                "policies": {
                                    "extAuthz": route_check,
                                    **outage_retry(),
                                },
                            }
                        ],
                    }
                ],
            }
        ],
        "policies": policies,
    }


# The managed enroller's role: it can read, and every transaction is read-only.
ENROLLER_ROLE = """
CREATE ROLE keeplane_enroller LOGIN PASSWORD :'password';
ALTER ROLE keeplane_enroller SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE keeplane TO keeplane_enroller;
GRANT USAGE ON SCHEMA public TO keeplane_enroller;
ALTER DEFAULT PRIVILEGES FOR ROLE keeplane IN SCHEMA public
  GRANT SELECT ON TABLES TO keeplane_enroller;
"""
ENROLLER_INIT = """#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 -U keeplane -d keeplane \\
  -v password="$(cat /trial/enroller-database-password)" -f /trial/enroller-role.sql
"""


class ReleaseInstall:
    """One disposable install. Use it as a context manager."""

    def __init__(self, mode, image, suffix=None):
        if mode not in MODES:
            raise ValueError("Choose existing or managed")
        self.mode, self.disposable = mode, True
        self.suffix = suffix or uuid.uuid4().hex[:8]
        self.project = f"keeplane-release-journey-{mode}-" + uuid.uuid4().hex[:8]
        # Bind mounts are read by the Docker host. In CI the suite runs in a
        # container that shares the checkout's path with the host, so the
        # install's files live inside the checkout, in the ignored .keeplane.
        parent = Path(
            os.environ.get("KEEPLANE_RELEASE_WORK_DIR", ROOT / ".keeplane")
        ).resolve()
        parent.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix=self.project + "-", dir=parent))
        self.app_port = free_port()
        self.runtime_port = free_port({self.app_port})
        self.runner_port = free_port({self.app_port, self.runtime_port})
        self.base = f"http://127.0.0.1:{self.app_port}"
        self.gateway = f"http://127.0.0.1:{self.runtime_port}/v1/chat/completions"
        self.runner_address = f"http://host.docker.internal:{self.runner_port}"
        self.listener = "developer-chat" if mode == "existing" else "keeplane-runtime"
        self.shared_cloud_key = mode == "managed"
        self.coder_model = "journey-coder-" + self.suffix
        self.cloud_model = "journey-cloud-" + self.suffix
        self.name = "a release install on PostgreSQL with two app copies and " + (
            "the customer's own gateway (existing mode)"
            if mode == "existing"
            else "the managed gateway and model enroller"
        )
        self.started = False
        try:
            self._write(image)
        except BaseException:
            shutil.rmtree(self.directory, ignore_errors=True)
            raise

    # Writing the install -------------------------------------------------

    def _write(self, image):
        images = json.loads((ROOT / "deploy/local/stack.lock.json").read_text())[
            "images"
        ]
        trial = self.directory / "trial"
        trial.mkdir(mode=0o755)
        self.values = {
            "first-admin-password": secrets.token_urlsafe(32),
            "gateway-admin-key": secrets.token_urlsafe(32),
            "gateway-runtime-key": secrets.token_urlsafe(32),
            "gateway-credential": secrets.token_urlsafe(32),
            "signing-key": secrets.token_urlsafe(64),
            "database-password": secrets.token_urlsafe(24),
            "enroller-database-password": secrets.token_urlsafe(24),
            "cloud-provider-key": secrets.token_urlsafe(32),
        }
        for name, value in self.values.items():
            (trial / name).write_text(value)
            # Synthetic values inside a private parent, read by other users.
            (trial / name).chmod(0o644)
        (trial / "enroller-role.sql").write_text(ENROLLER_ROLE)
        (trial / "enroller-role.sh").write_text(ENROLLER_INIT)
        for name in ("enroller-role.sql", "enroller-role.sh"):
            (trial / name).chmod(0o755 if name.endswith(".sh") else 0o644)
        tls = self.directory / "tls"
        load("keeplane_up", ROOT / "deploy/local/up.py").preview_tls(tls, days=2)
        tls.chmod(0o755)
        for path in tls.iterdir():
            path.chmod(0o644)
        if self.mode == "existing":
            (trial / "gateway.yaml").write_text(
                json.dumps(
                    customer_gateway(
                        self.values["gateway-admin-key"],
                        [self.coder_model],
                        [self.cloud_model],
                    )
                )
            )
        image_id = self.command(
            "docker", "image", "inspect", image, "--format", "{{.Id}}"
        )
        fixture = str(Path(__file__).resolve()) + ":/fixture.py:ro"
        control_plane = str(ROOT / "components/control-plane") + ":/app:ro"
        admin_ui = (
            str(
                Path(
                    os.environ.get(
                        "KEEPLANE_ADMIN_UI_DIR", ROOT / "components/admin-ui"
                    )
                ).resolve()
            )
            + ":/ui:ro"
        )
        trial_mount = str(trial) + ":/trial:ro"
        ca = str(tls / "ca.pem") + ":/run/preview-ca/ca.pem:ro"
        host = {"extra_hosts": ["host.docker.internal:host-gateway"]}
        database = {
            "KEEPLANE_DATABASE_HOST": "database",
            "KEEPLANE_DATABASE_NAME": "keeplane",
            "KEEPLANE_DATABASE_USER": "keeplane",
            "KEEPLANE_DATABASE_PASSWORD_FILE": "/trial/database-password",
            # TLS to PostgreSQL is checked by the chart and deployment cases;
            # this disposable network has no certificates.
            "KEEPLANE_DATABASE_SSLMODE": "disable",
        }
        environment = {
            "PYTHONDONTWRITEBYTECODE": "1",
            "GATEWAY_MODE": self.mode,
            "DJANGO_SECRET_KEY_FILE": "/trial/signing-key",
            "FIRST_ADMIN_PASSWORD_FILE": "/trial/first-admin-password",
            "PUBLIC_ORIGIN": self.base,
            "GATEWAY_URL": "http://gateway:4000",
            "GATEWAY_ADMIN_KEY_FILE": "/trial/gateway-admin-key",
            "GATEWAY_RUNTIME_KEY_FILE": "/trial/gateway-runtime-key",
            "KEEPLANE_CLI_OAUTH_ENABLED": "1",
            "KEEPLANE_GATEWAY_PUBLIC_URL": f"http://127.0.0.1:{self.runtime_port}/v1",
            "PREVIEW_RUNNER_URLS": self.runner_address,
            "PREVIEW_OPENAI_BASE_URL": "https://cloud-provider:18443/v1",
            "PREVIEW_ANTHROPIC_BASE_URL": "https://cloud-provider:18443/v1",
            # Only the fixture provider's test CA, as in the Docker preview.
            "SSL_CERT_FILE": "/run/preview-ca/ca.pem",
            **database,
        }
        volumes = [trial_mount, control_plane, admin_ui, ca]
        if self.mode == "existing":
            environment["RUNTIME_AUTHORIZER_KEY_FILE"] = "/trial/gateway-credential"
        else:
            environment.update(
                {
                    "RUNTIME_AUTHORIZER_KEY_FILE": "/installed/callback-key",
                    "RUNTIME_GUARD_MANIFEST_FILE": "/installed/manifest.json",
                    "GATEWAY_FILE_CONFIG": "/installed/gateway.json",
                    "PROVIDER_KEY_DIR": "/provider-keys",
                }
            )
            volumes += [
                "runtime-installation:/installed:ro",
                "provider-keys:/provider-keys",
            ]
        app = {
            "image": image_id,
            "volumes": volumes,
            "environment": environment,
            "read_only": True,
            "tmpfs": ["/tmp:uid=65532,gid=65532,mode=700"],
            **host,
        }
        setup = (
            "python manage.py migrate --noinput && python manage.py bootstrap"
            " && python manage.py register_cli_client"
            " && python manage.py register_cli_client --device"
        )
        services = {
            "database": {
                "image": images["postgres"],
                "environment": {
                    "POSTGRES_USER": "keeplane",
                    "POSTGRES_DB": "keeplane",
                    "POSTGRES_PASSWORD_FILE": "/trial/database-password",
                },
                "volumes": [
                    trial_mount,
                    str(trial / "enroller-role.sh")
                    + ":/docker-entrypoint-initdb.d/enroller-role.sh:ro",
                ],
                "tmpfs": ["/var/lib/postgresql", "/var/run/postgresql"],
                "healthcheck": {
                    "test": ["CMD", "pg_isready", "-U", "keeplane", "-d", "keeplane"],
                    "interval": "1s",
                    "retries": 90,
                },
            },
            "volume-init": {
                "image": images["python_fixture"],
                "user": "0",
                "command": [
                    "sh",
                    "-ec",
                    "chown 65532:65532 /data /provider-keys && chmod 700 /provider-keys",
                ],
                "volumes": ["gateway-data:/data", "provider-keys:/provider-keys"],
            },
            "app-setup": {
                **app,
                "command": ["sh", "-ec", setup],
                "depends_on": {"database": {"condition": "service_healthy"}},
            },
            "app": {
                # One address for the browser, the CLI and the gateway's checks.
                "image": images["python_fixture"],
                "command": ["python", "/fixture.py", "front", *COPIES],
                "volumes": [fixture],
                "read_only": True,
                "tmpfs": ["/state:mode=700"],
                "ports": [f"127.0.0.1:{self.app_port}:3000"],
                "depends_on": list(COPIES),
            },
            "cloud-provider": {
                "image": images["python_fixture"],
                "command": ["python", "/cloud_provider.py"],
                "environment": {
                    "TRIAL_KEY_FILE": "/trial/cloud-provider-key",
                    "TLS_CERT_FILE": "/run/tls/provider.pem",
                    "TLS_KEY_FILE": "/run/tls/provider.key",
                },
                "volumes": [
                    str(ROOT / "tests/fixtures/cloud_provider.py")
                    + ":/cloud_provider.py:ro",
                    trial_mount,
                    str(tls) + ":/run/tls:ro",
                ],
            },
            "model": {
                "image": images["python_fixture"],
                "command": ["python", "/mock_model.py", "--port", "18080"],
                "volumes": [
                    str(ROOT / "tests/fixtures/mock_model.py") + ":/mock_model.py:ro"
                ],
                "read_only": True,
            },
        }
        gateway = {
            "image": images["agentgateway"],
            "read_only": True,
            # The disposable network is IPv4 only.
            "environment": {
                "IPV6_ENABLED": "false",
                "SSL_CERT_FILE": "/run/preview-ca/ca.pem",
            },
            "depends_on": {
                "volume-init": {"condition": "service_completed_successfully"},
                "model": {"condition": "service_started"},
                "cloud-provider": {"condition": "service_started"},
            },
            "ports": [f"127.0.0.1:{self.runtime_port}:5000"],
            **host,
        }
        if self.mode == "existing":
            gateway["command"] = ["-f", "/trial/gateway.yaml"]
            gateway["volumes"] = [trial_mount, ca, "gateway-data:/data"]
        else:
            gateway["command"] = ["-f", "/installed/gateway.json"]
            gateway["volumes"] = [
                ca,
                "gateway-data:/data",
                "runtime-installation:/installed:ro",
                "provider-keys:/provider-keys:ro",
            ]
            gateway["depends_on"]["runtime-init"] = {
                "condition": "service_completed_successfully"
            }
            secrets_dir = self.directory / "runtime-secrets"
            secrets_dir.mkdir(mode=0o755)
            for name in ("gateway-admin-key", "gateway-runtime-key"):
                shutil.copyfile(trial / name, secrets_dir / name)
                (secrets_dir / name).chmod(0o644)
            services["runtime-init"] = {
                "image": images["python_fixture"],
                "user": "0",
                "command": ["python", "/prepare_runtime.py"],
                "volumes": [
                    "runtime-installation:/installed",
                    str(secrets_dir) + ":/run/secrets:ro",
                    str(ROOT / "deploy/local/prepare_runtime.py")
                    + ":/prepare_runtime.py:ro",
                    str(ROOT / "deploy/local/runtime-base.json")
                    + ":/runtime-base.json:ro",
                ],
            }
            # ADR 027: the only writer of the guard. No port; its own
            # read-only database role; the gateway's network namespace.
            enroller = json.loads(json.dumps(app))
            enroller.pop("extra_hosts")
            enroller["environment"].update(
                {
                    "GATEWAY_URL": "http://127.0.0.1:4000",
                    "KEEPLANE_DATABASE_USER": "keeplane_enroller",
                    "KEEPLANE_DATABASE_PASSWORD_FILE": "/trial/enroller-database-password",
                    "KEEPLANE_DATABASE_READ_ONLY": "1",
                }
            )
            enroller["volumes"] = [
                trial_mount,
                control_plane,
                "runtime-installation:/installed",
                "provider-keys:/provider-keys:ro",
            ]
            enroller.update(
                {
                    "command": ["python", "manage.py", "run_model_enroller"],
                    "network_mode": "service:gateway",
                    "depends_on": {
                        "gateway": {"condition": "service_started"},
                        "app-setup": {"condition": "service_completed_successfully"},
                    },
                    "restart": "unless-stopped",
                }
            )
            services["model-enroller"] = enroller
            services["app-setup"]["depends_on"]["runtime-init"] = {
                "condition": "service_completed_successfully"
            }
        services["gateway"] = gateway
        for name in COPIES:
            services[name] = {
                **app,
                "depends_on": {
                    "database": {"condition": "service_healthy"},
                    "app-setup": {"condition": "service_completed_successfully"},
                    "gateway": {"condition": "service_started"},
                },
            }
        for name, service in services.items():
            service.update(
                {"pull_policy": "never", "security_opt": ["no-new-privileges:true"]}
            )
            if name not in ("database", "volume-init", "runtime-init"):
                # PostgreSQL's entrypoint, chown and the installer's chown need
                # their default capabilities.
                service["cap_drop"] = ["ALL"]
        named = {"gateway-data": {}, "provider-keys": {}}
        if self.mode == "managed":
            named["runtime-installation"] = {}
        self.compose_file = self.directory / "compose.json"
        self.compose_file.write_text(
            json.dumps({"services": services, "volumes": named}, indent=1)
        )

    # Running it ------------------------------------------------------------

    def redact(self, text):
        for value in self.values.values():
            text = text.replace(value, "[redacted]")
        return text

    def command(self, *args, check=True, timeout=300, **kwargs):
        result = subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=timeout, **kwargs
        )
        if check and result.returncode:
            raise RuntimeError(
                "Disposable install command failed: "
                + self.redact(result.stderr + result.stdout)[-2000:]
            )
        return result.stdout.strip()

    def compose(self, *args, **kwargs):
        return self.command(
            "docker",
            "compose",
            "-p",
            self.project,
            "-f",
            str(self.compose_file),
            *args,
            **kwargs,
        )

    def __enter__(self):
        self.started = True
        try:
            self.compose("up", "-d", "--wait", "database", timeout=300)
            self.compose("up", "-d", "app", timeout=300)
            self.wait_ready()
            if self.mode == "managed":
                self.compose("up", "-d", "model-enroller", timeout=300)
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        try:
            if self.started:
                self.compose(
                    "down", "--volumes", "--remove-orphans", check=False, timeout=180
                )
                self.started = False
        finally:
            shutil.rmtree(self.directory, ignore_errors=True)

    def logs(self, tail=80):
        return self.redact(
            self.compose("logs", "--no-color", "--tail", str(tail), check=False)
        )

    def status(self, path):
        try:
            with build_opener(ProxyHandler({})).open(
                self.base + path, timeout=3
            ) as response:
                return response.status
        except HTTPError as error:
            error.close()
            return error.code
        except (URLError, OSError):
            return None

    def wait_ready(self, timeout=180):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # Every copy, not just the one the next request reaches.
            if all(self.status("/health/ready") == 200 for _ in COPIES):
                return
            time.sleep(0.5)
        raise RuntimeError("The app copies did not become ready:\n" + self.logs())

    # What the journey reads ---------------------------------------------------

    def secret(self, name):
        if name not in ("first-admin-password", "cloud-provider-key"):
            raise KeyError(name)
        return self.values[name]

    def exec(self, service, *args, timeout=60, front=False):
        """``docker compose exec -T`` in one of the install's containers.

        ``app`` is the first app copy, as the journey runs Django commands
        there; ``front=True`` reaches the address in front of the copies.
        """
        service = COPIES[0] if service == "app" and not front else service
        return subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                self.project,
                "-f",
                str(self.compose_file),
                "exec",
                "-T",
                service,
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def gateway_requests(self):
        """How many requests the developer listener has logged, or None."""
        logs = subprocess.run(
            [
                "docker",
                "compose",
                "-p",
                self.project,
                "-f",
                str(self.compose_file),
                "logs",
                "--no-color",
                "--no-log-prefix",
                "gateway",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if logs.returncode:
            return None
        listener = "listener=" + self.listener
        return sum(
            "request" in line.split() and listener in line.split()
            for line in logs.stdout.splitlines()
        )

    def enroller_reports(self):
        logs = self.exec_logs("model-enroller")
        return [
            line.strip()
            for line in logs.splitlines()
            if line.strip().startswith(
                (
                    "No model is enrolled",
                    "Protected access is",
                    "A model change is waiting",
                )
            )
        ]

    def exec_logs(self, service):
        return self.compose(
            "logs", "--no-color", "--no-log-prefix", service, check=False, timeout=60
        )

    def settled(self, expected, timeout):
        """Whether the enroller's latest report is one of ``expected``.

        A customer-run gateway has no enroller: Keeplane's checks read the
        saved approvals on every request, so a change applies at once.
        """
        if self.mode == "existing":
            return True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            reports = self.enroller_reports()
            if reports and reports[-1] in expected:
                return True
            time.sleep(1)
        return False

    def copies_served(self):
        """How many requests each app copy answered through the one address."""
        result = self.exec("app", "cat", "/state/copies.json", front=True)
        if result.returncode:
            return None
        try:
            return json.loads(result.stdout)
        except ValueError:
            return None


# Inside the containers ---------------------------------------------------

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


def front_server(copies, address=("0.0.0.0", 3000), record=Path("/state/copies.json")):
    """One address for the app copies: each request goes to the next copy.

    Each copy is a host, on port 3000, or ``host:port``. What each copy
    answered is counted in ``record``.
    """
    served = dict.fromkeys(copies, 0)
    lock = threading.Lock()
    turn = [0]
    record.write_text(json.dumps(served))

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def relay(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            with lock:
                copy = copies[turn[0] % len(copies)]
                turn[0] += 1
            headers = {
                name: value
                for name, value in self.headers.items()
                if name.lower() not in HOP_BY_HOP
            }
            host, _, port = copy.partition(":")
            connection = HTTPConnection(host, int(port or 3000), timeout=120)
            try:
                connection.request(self.command, self.path, body, headers)
                answer = connection.getresponse()
                data = answer.read()
            except OSError:
                self.send_response(502)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            finally:
                connection.close()
            with lock:
                served[copy] += 1
                record.write_text(json.dumps(served))
            self.send_response(answer.status)
            for name, value in answer.getheaders():
                # This server sends its own Server and Date.
                if name.lower() not in HOP_BY_HOP | {"server", "date"}:
                    self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = relay

    return ThreadingHTTPServer(address, Handler)


if __name__ == "__main__":
    if sys.argv[1] == "front":
        front_server(sys.argv[2:]).serve_forever()
    else:
        raise SystemExit("Choose front")
