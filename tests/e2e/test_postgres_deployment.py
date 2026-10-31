"""Exercise the PostgreSQL chart, real gateway, TLS, roles and durable restore."""

import pytest

import argparse
import base64
import copy
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import tempfile
import time
import traceback
import uuid
from urllib.request import HTTPSHandler, HTTPCookieProcessor, build_opener
from urllib.error import URLError

from tests.support.client import Browser
from tests.support.kind_images import pin_loaded_image
from tests.support.helm import require_helm


ROOT = Path(__file__).resolve().parents[2]
KUBECONFIG = os.environ.get(
    "KEEPLANE_NETPOL_KUBECONFIG", "/private/tmp/keeplane-netpol-kubeconfig"
)
HELM = require_helm()
IMAGE = "keeplane-preview:postgres-local"
POSTGRES = (
    "postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea"
)


def run_cases():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a fresh evidence output")
    namespace = "keeplane-pg-" + uuid.uuid4().hex[:8]
    result = {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "namespace": namespace,
        "cases": [],
        "completed": False,
        "fixture_removed": False,
        "release_approved": False,
        "limits": [
            "Single-node kind PVC evidence is not a production storage or database HA guarantee.",
            "Account database TLS is tested; the disposable gateway database is a separate HTTP-network fixture.",
            "No real provider credential, project-bound execution or final-destination policy is tested.",
            "Existing review previews and their databases are not replaced.",
        ],
    }
    processes = []
    created = False
    stage = "context"

    def run(*command, input_data=None, check=True):
        item = subprocess.run(
            command, cwd=ROOT, input=input_data, capture_output=True, timeout=360
        )
        if check and item.returncode:
            # Do not include SQL, credentials, cookies or command arguments in errors.
            result["failure_frames"] = [
                line.strip()
                for line in item.stderr.decode(errors="replace").splitlines()
                if re.match(r'\s*File "[^"\n]+", line \d+', line)
            ]
            raise RuntimeError(command[0] + " exited " + str(item.returncode))
        return item

    def kube(*arguments, **kwargs):
        return run("kubectl", "--kubeconfig", KUBECONFIG, *arguments, **kwargs)

    def apply(item):
        kube("-n", namespace, "apply", "-f", "-", input_data=json.dumps(item).encode())

    def secret(name, values):
        apply(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": name},
                "data": {
                    key: base64.b64encode(
                        value if isinstance(value, bytes) else value.encode()
                    ).decode()
                    for key, value in values.items()
                },
            }
        )

    def forward(target, remote, ns=None):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen(
            [
                "kubectl",
                "--kubeconfig",
                KUBECONFIG,
                "-n",
                ns or namespace,
                "port-forward",
                target,
                str(port) + ":" + str(remote),
                "--address=127.0.0.1",
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(process)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return port
            except OSError:
                if process.poll() is not None:
                    break
                time.sleep(0.2)
        raise RuntimeError("Port-forward did not start")

    def record(identifier, action):
        nonlocal stage
        stage = identifier
        observed = action()
        result["cases"].append(
            {"case": identifier, "verdict": "pass", "observed": observed}
        )
        print(identifier + ": PASS", flush=True)

    def sql(statement, database="postgres"):
        return (
            kube(
                "-n",
                namespace,
                "exec",
                "-i",
                "deploy/db",
                "--",
                "psql",
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                database,
                "-At",
                input_data=statement.encode(),
            )
            .stdout.decode()
            .strip()
        )

    def ready(deployment):
        kube(
            "-n",
            namespace,
            "rollout",
            "status",
            "deployment/" + deployment,
            "--timeout=240s",
        )

    def app_script(script, deployment="managed-app"):
        script = "import sys;sys.path.insert(0,'/app')\n" + script
        return json.loads(
            kube(
                "-n",
                namespace,
                "exec",
                "-i",
                "deploy/" + deployment,
                "--",
                "python",
                "-",
                input_data=script.encode(),
            ).stdout
        )

    def chart(release, values, upgrade=False):
        path = directory / (release + ".json")
        path.write_text(json.dumps(values))
        run(
            HELM,
            "--kubeconfig",
            KUBECONFIG,
            "upgrade" if upgrade else "install",
            release,
            "deploy/helm/keeplane",
            "--namespace",
            namespace,
            "-f",
            str(path),
            "--wait",
            "--timeout",
            "300s",
        )

    def database(name, admin_secret, tls=False):
        volumes = [
            {"name": "data", "persistentVolumeClaim": {"claimName": name + "-data"}}
        ]
        mounts = [{"name": "data", "mountPath": "/var/lib/postgresql/data"}]
        command = ["postgres"]
        if tls:
            volumes += [
                {
                    "name": "tls",
                    "secret": {"secretName": "db-tls", "defaultMode": 0o640},
                },
                {"name": "hba", "configMap": {"name": "db-hba"}},
            ]
            mounts += [
                {"name": "tls", "mountPath": "/run/db-tls", "readOnly": True},
                {"name": "hba", "mountPath": "/etc/db-hba", "readOnly": True},
            ]
            command += [
                "-c",
                "ssl=on",
                "-c",
                "ssl_cert_file=/run/db-tls/tls.crt",
                "-c",
                "ssl_key_file=/run/db-tls/tls.key",
                "-c",
                "hba_file=/etc/db-hba/pg_hba.conf",
            ]
        apply(
            {
                "apiVersion": "v1",
                "kind": "PersistentVolumeClaim",
                "metadata": {"name": name + "-data"},
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "resources": {"requests": {"storage": "1Gi"}},
                },
            }
        )
        apply(
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": name},
                "spec": {
                    "replicas": 1,
                    "strategy": {"type": "Recreate"},
                    "selector": {"matchLabels": {"app": name}},
                    "template": {
                        "metadata": {"labels": {"app": name}},
                        "spec": {
                            "automountServiceAccountToken": False,
                            "securityContext": {"fsGroup": 70},
                            "containers": [
                                {
                                    "name": "postgres",
                                    "image": POSTGRES,
                                    "args": command,
                                    "env": [
                                        {
                                            "name": "POSTGRES_PASSWORD",
                                            "valueFrom": {
                                                "secretKeyRef": {
                                                    "name": admin_secret,
                                                    "key": "password",
                                                }
                                            },
                                        },
                                        {
                                            "name": "PGDATA",
                                            "value": "/var/lib/postgresql/data/pgdata",
                                        },
                                    ],
                                    "readinessProbe": {
                                        "exec": {
                                            "command": ["pg_isready", "-U", "postgres"]
                                        },
                                        "periodSeconds": 2,
                                    },
                                    "volumeMounts": mounts,
                                }
                            ],
                            "volumes": volumes,
                        },
                    },
                },
            }
        )
        apply(
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": name},
                "spec": {
                    "selector": {"app": name},
                    "ports": [{"port": 5432, "targetPort": 5432}],
                },
            }
        )
        ready(name)

    context = kube("config", "current-context").stdout.decode().strip()
    if context != "kind-keeplane-netpol":
        raise RuntimeError("Only the isolated kind-keeplane-netpol context is allowed")
    result["context"] = context
    with tempfile.TemporaryDirectory(prefix=namespace + "-") as temporary:
        directory = Path(temporary)
        directory.chmod(0o700)
        try:
            stage = "certificates-and-secrets"
            kube("create", "namespace", namespace)
            created = True
            result["app_image"] = (
                run("docker", "image", "inspect", IMAGE, "--format", "{{.Id}}")
                .stdout.decode()
                .strip()
            )
            run("kind", "load", "docker-image", IMAGE, "--name", "keeplane-netpol")
            pinned_image = pin_loaded_image(
                run, "docker.io/library/" + IMAGE, "keeplane-netpol")
            result["app_manifest_reference"] = pinned_image
            # Both endpoints have their own leaf certificate from a disposable CA.
            run(
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "2",
                "-subj",
                "/CN=Keeplane fixture CA",
                "-keyout",
                str(directory / "ca.key"),
                "-out",
                str(directory / "ca.crt"),
            )
            for name, hostname in (("db", "db"), ("edge", "localhost")):
                extension = directory / (name + ".ext")
                extension.write_text(
                    "subjectAltName=DNS:" + hostname + "\nextendedKeyUsage=serverAuth\n"
                )
                run(
                    "openssl",
                    "req",
                    "-new",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-subj",
                    "/CN=" + hostname,
                    "-keyout",
                    str(directory / (name + ".key")),
                    "-out",
                    str(directory / (name + ".csr")),
                )
                run(
                    "openssl",
                    "x509",
                    "-req",
                    "-in",
                    str(directory / (name + ".csr")),
                    "-CA",
                    str(directory / "ca.crt"),
                    "-CAkey",
                    str(directory / "ca.key"),
                    "-CAcreateserial",
                    "-days",
                    "2",
                    "-extfile",
                    str(extension),
                    "-out",
                    str(directory / (name + ".crt")),
                )
                (directory / (name + ".key")).chmod(0o600)
            password, signing, runtime_key, admin_key = [
                secrets.token_urlsafe(48) for _ in range(4)
            ]
            db_password, migrate_password = (
                secrets.token_urlsafe(48),
                secrets.token_urlsafe(48),
            )
            secret("app-db", {"password": db_password})
            secret("migrate-db", {"password": migrate_password})
            secret(
                "identity",
                {"signing-secret": signing, "first-admin-password": password},
            )
            secret("db-admin", {"password": secrets.token_urlsafe(48)})
            secret("gateway-db", {"password": secrets.token_urlsafe(48)})
            secret("database-ca", {"ca.crt": (directory / "ca.crt").read_bytes()})
            secret(
                "db-tls",
                {
                    "tls.crt": (directory / "db.crt").read_bytes(),
                    "tls.key": (directory / "db.key").read_bytes(),
                },
            )
            secret(
                "edge-tls",
                {
                    "tls.crt": (directory / "edge.crt").read_bytes(),
                    "tls.key": (directory / "edge.key").read_bytes(),
                },
            )
            secret(
                "gateway-keys",
                {
                    "runtime-key": runtime_key,
                    "admin-key": admin_key,
                    "runtime-key-hash": "sha256:"
                    + hashlib.sha256(runtime_key.encode()).hexdigest(),
                    "admin-key-hash": "sha256:"
                    + hashlib.sha256(admin_key.encode()).hexdigest(),
                },
            )
            apply(
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": "db-hba"},
                    "data": {
                        "pg_hba.conf": "local all all trust\nhostnossl all all 0.0.0.0/0 reject\nhostssl all all 0.0.0.0/0 scram-sha-256\n"
                    },
                }
            )
            stage = "database-and-roles"
            database("db", "db-admin", tls=True)
            database("gatewaydb", "gateway-db")
            sql(
                "CREATE ROLE keeplane_migrate LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD '"
                + migrate_password
                + "';\n"
                "CREATE ROLE keeplane_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD '"
                + db_password
                + "';\n"
                "CREATE DATABASE keeplane OWNER keeplane_migrate;\nREVOKE ALL ON DATABASE keeplane FROM PUBLIC;\nGRANT CONNECT ON DATABASE keeplane TO keeplane_app;"
            )
            sql(
                "REVOKE CREATE ON SCHEMA public FROM PUBLIC;\nGRANT USAGE ON SCHEMA public TO keeplane_app;\n"
                "ALTER DEFAULT PRIVILEGES FOR ROLE keeplane_migrate IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO keeplane_app;\n"
                "ALTER DEFAULT PRIVILEGES FOR ROLE keeplane_migrate IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO keeplane_app;",
                "keeplane",
            )
            apply(
                {
                    "apiVersion": "v1",
                    "kind": "PersistentVolumeClaim",
                    "metadata": {"name": "provider-keys"},
                    "spec": {
                        "accessModes": ["ReadWriteOnce"],
                        "resources": {"requests": {"storage": "1Gi"}},
                    },
                }
            )
            kube(
                "-n",
                namespace,
                "create",
                "configmap",
                "model-fixture",
                "--from-file=mock_model.py=tests/fixtures/mock_model.py",
            )
            kube("-n", namespace, "apply", "-f", "deploy/local/model-fixture.yaml")
            ready("model")
            tls_port = forward("deploy/ingress-nginx-controller", 443, "ingress-nginx")
            origin = "https://localhost:" + str(tls_port)
            values = {
                "app": {
                    "image": pinned_image,
                    "pullPolicy": "Never",
                    "replicaCount": 2,
                    "runnerUrls": "http://model:18080",
                    "postgres": {
                        "enabled": True,
                        "host": "db",
                        "database": "keeplane",
                        "user": "keeplane_app",
                        "credentialsSecret": "app-db",
                        "identitySecret": "identity",
                        "caSecret": "database-ca",
                        "providerKeysClaim": "provider-keys",
                        "publicOrigin": origin,
                        "publicOriginAliases": origin,
                        "migration": {
                            "user": "keeplane_migrate",
                            "credentialsSecret": "migrate-db",
                        },
                    },
                },
                "gateway": {
                    "mode": "managed",
                    "install": True,
                    "keysSecret": "gateway-keys",
                    "copies": 2,
                },
                "ingress": {
                    "enabled": True,
                    "className": "nginx",
                    "host": "localhost",
                    "tlsSecretName": "edge-tls",
                },
                "agentgateway-standalone": {
                    "database": {
                        "postgres": {
                            "url": "postgresql://postgres:${GATEWAY_DB_PASSWORD}@gatewaydb:5432/postgres"
                        }
                    },
                    "extraEnv": [
                        {
                            "name": "GATEWAY_DB_PASSWORD",
                            "valueFrom": {
                                "secretKeyRef": {
                                    "name": "gateway-db",
                                    "key": "password",
                                }
                            },
                        },
                        {
                            "name": "GATEWAY_RUNTIME_KEY_HASH",
                            "valueFrom": {
                                "secretKeyRef": {
                                    "name": "gateway-keys",
                                    "key": "runtime-key-hash",
                                }
                            },
                        },
                        {
                            "name": "GATEWAY_ADMIN_KEY_HASH",
                            "valueFrom": {
                                "secretKeyRef": {
                                    "name": "gateway-keys",
                                    "key": "admin-key-hash",
                                }
                            },
                        },
                    ],
                    "config": {
                        "gateways": {"default": {"port": 4000}},
                        "ui": {
                            "gateways": "default",
                            "policies": {
                                "apiKey": {
                                    "mode": "strict",
                                    "keys": [{"keyHash": "${GATEWAY_ADMIN_KEY_HASH}"}],
                                }
                            },
                        },
                        "llm": {
                            "policies": {
                                "apiKey": {
                                    "mode": "strict",
                                    "keys": [
                                        {"keyHash": "${GATEWAY_RUNTIME_KEY_HASH}"}
                                    ],
                                }
                            },
                            "models": [
                                {
                                    "name": "local-fixture",
                                    "provider": {
                                        "custom": {"formats": [{"type": "completions"}]}
                                    },
                                    "params": {
                                        "model": "mock-local",
                                        "baseUrl": "http://model:18080/v1",
                                    },
                                }
                            ],
                        },
                    },
                },
            }
            stage = "helm-install"
            chart("managed", values)
            browser = Browser(origin)
            browser.opener = build_opener(
                HTTPCookieProcessor(browser.cookies),
                HTTPSHandler(
                    context=ssl.create_default_context(cafile=str(directory / "ca.crt"))
                ),
            )

            def signed_in():
                # Helm waits for pods, while the existing ingress controller
                # may still be applying its new TLS certificate and route.
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    try:
                        status, url, _ = browser.page("/")
                        if status == 200 and url == origin + "/sign-in":
                            break
                        result["last_ingress_status"] = status
                    except (URLError, OSError):
                        pass
                    time.sleep(0.5)
                assert browser.login("first-admin", password)[0] == 200
                identity = browser.fetch("/api/identity")[1]
                assert uuid.UUID(identity["id"])
                assert browser.page("/app/")[0] == 200
                return {"https_sign_in": 200, "uuid_identity": True, "app_copies": 2}

            record("PGDEPLOY-01", signed_in)
            session_id = browser.fetch("/api/identity")[1]["id"]

            def transport_and_roles():
                return app_script("""import os,json,django,psycopg
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings");django.setup()
from django.db import connection
with connection.cursor() as c:
 c.execute("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()");assert c.fetchone()[0]
 c.execute("SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user");assert c.fetchone()==(False,False,False)
refused=[]
for statement in ("CREATE TABLE public.forbidden(id int)","ALTER TABLE accounts_user ADD COLUMN forbidden int","CREATE ROLE forbidden"):
 try:
  with connection.cursor() as c:c.execute(statement)
 except Exception as error:refused.append(getattr(error.__cause__,"sqlstate",None)=="42501")
 else:refused.append(False)
assert all(refused)
parameters=connection.get_connection_params();parameters.pop("context",None)
tls_refusals=[]
for override,expected in (({"host":"wrong.example.test","hostaddr":__import__("socket").gethostbyname("db")},"does not match host name"),({"sslrootcert":"/etc/ssl/cert.pem"},"certificate verify failed"),({"sslmode":"disable"},"pg_hba.conf rejects connection")):
 try:psycopg.connect(**dict(parameters,**override)).close()
 except psycopg.OperationalError as error:tls_refusals.append(expected in str(error))
 else:tls_refusals.append(False)
assert all(tls_refusals)
print(json.dumps({"tls_active":True,"runtime_ddl_and_role_changes_refused":len(refused),"hostname_ca_and_plaintext_refused":len(tls_refusals)}))
""")

            record("PGDEPLOY-02", transport_and_roles)

            def model_call():
                assert (
                    browser.fetch(
                        "/api/models/local-fixture/setup",
                        {"key_choice": "none", "approved_classes": []},
                        method="POST",
                    )[0]
                    == 200
                )
                assert (
                    browser.fetch(
                        "/api/models",
                        {
                            "name": "registered-fixture",
                            "source": "fixture",
                            "model": "mock-local",
                            "approved_classes": [],
                        },
                        method="POST",
                    )[0]
                    == 200
                )
                status, answer, _ = browser.fetch(
                    "/api/ask",
                    {
                        "model": "registered-fixture",
                        "prompt": "fixture deployment answer",
                    },
                )
                assert status == 200 and "mock answer" in json.dumps(answer)
                return {
                    "model_setup": 200,
                    "database_model_registration": 200,
                    "real_gateway_answer": 200,
                }

            record("PGDEPLOY-03", model_call)
            pods = json.loads(
                kube(
                    "-n",
                    namespace,
                    "get",
                    "pods",
                    "-l",
                    "app=managed-app",
                    "-o",
                    "json",
                ).stdout
            )["items"]

            def direct(port, path, payload=None, method="GET"):
                headers = {
                    "Cookie": "; ".join(
                        cookie.name + "=" + cookie.value for cookie in browser.cookies
                    ),
                    "Origin": origin,
                }
                if payload is not None:
                    headers.update(
                        {
                            "Content-Type": "application/json",
                            "X-CSRFToken": browser.fetch("/api/auth-options")[1][
                                "csrf_token"
                            ],
                            "X-Keeplane-Action": "1",
                        }
                    )
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
                try:
                    connection.request(
                        method,
                        path,
                        None if payload is None else json.dumps(payload),
                        headers,
                    )
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()

            def shared_copies():
                statuses = [
                    direct(
                        forward("pod/" + pod["metadata"]["name"], 3000), "/api/identity"
                    )
                    for pod in pods
                ]
                assert len(statuses) == 2 and all(
                    status == 200 and identity["id"] == session_id
                    for status, identity in statuses
                )
                deployment = json.loads(
                    kube(
                        "-n", namespace, "get", "deploy/managed-app", "-o", "json"
                    ).stdout
                )
                assert "migrate-db" not in json.dumps(deployment)
                return {
                    "shared_session_on_each_copy": True,
                    "migration_secret_in_app": False,
                }

            record("PGDEPLOY-04", shared_copies)
            existing = copy.deepcopy(values)
            existing["ingress"]["enabled"] = False
            existing["gateway"].update(
                mode="existing", install=False, url="http://managed:4000"
            )
            stage = "existing-install"
            chart("customer", existing)

            def existing_call():
                port = forward("deploy/customer-app", 3000)
                assert direct(port, "/api/identity")[1]["id"] == session_id
                assert direct(port, "/api/models")[0] == 200
                status, answer = direct(
                    port,
                    "/api/ask",
                    {
                        "model": "registered-fixture",
                        "prompt": "existing gateway fixture",
                    },
                    "POST",
                )
                assert status == 200 and "mock answer" in json.dumps(answer)
                absent = (
                    kube(
                        "-n", namespace, "get", "deployment/customer", check=False
                    ).returncode
                    != 0
                )
                assert absent
                return {
                    "existing_gateway_answer": 200,
                    "second_gateway_installed": False,
                }

            record("PGDEPLOY-05", existing_call)

            def durable_restart():
                kube("-n", namespace, "rollout", "restart", "deployment/db")
                ready("db")
                kube("-n", namespace, "rollout", "restart", "deployment/managed-app")
                ready("managed-app")
                assert browser.fetch("/api/identity")[1]["id"] == session_id
                assert browser.fetch("/api/models")[1]["models"][0]["approved"] is True
                return {
                    "database_pod_replaced": True,
                    "app_pods_replaced": True,
                    "identity_session_approval_preserved": True,
                }

            record("PGDEPLOY-06", durable_restart)

            def restore():
                dump = kube(
                    "-n",
                    namespace,
                    "exec",
                    "deploy/db",
                    "--",
                    "pg_dump",
                    "-U",
                    "postgres",
                    "-d",
                    "keeplane",
                    "-Fc",
                ).stdout
                sql(
                    "CREATE DATABASE restored OWNER keeplane_migrate;\nREVOKE ALL ON DATABASE restored FROM PUBLIC;\nGRANT CONNECT ON DATABASE restored TO keeplane_app;"
                )
                kube(
                    "-n",
                    namespace,
                    "exec",
                    "-i",
                    "deploy/db",
                    "--",
                    "pg_restore",
                    "-U",
                    "postgres",
                    "-d",
                    "restored",
                    input_data=dump,
                )
                values["app"]["postgres"]["database"] = existing["app"]["postgres"][
                    "database"
                ] = "restored"
                chart("managed", values, upgrade=True)
                chart("customer", existing, upgrade=True)
                assert browser.fetch("/api/identity")[1]["id"] == session_id
                assert browser.fetch("/api/audit/records")[1]["total"] >= 1
                assert browser.fetch("/api/models")[1]["models"][0]["approved"] is True
                return {
                    "fresh_database_restored": True,
                    "both_installs_reconfigured": True,
                    "session_audit_approval_preserved": True,
                }

            record("PGDEPLOY-07", restore)
            result["runtime_package"] = app_script(
                'import json;print(open("/usr/share/keeplane/postgres-package.json").read())'
            )
            result["completed"] = True
        except Exception as error:
            result["failure_stage"] = stage
            result["fixture_error"] = type(error).__name__ + ": " + str(error)
            result["fixture_frames"] = [
                {"file": Path(frame.filename).name, "line": frame.lineno}
                for frame in traceback.extract_tb(error.__traceback__)
            ]
        finally:
            for process in processes:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if created:
                deleted = kube(
                    "delete", "namespace", namespace, "--wait=true", check=False
                )
                result["fixture_removed"] = (
                    deleted.returncode == 0
                    and kube("get", "namespace", namespace, check=False).returncode != 0
                )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    print(
        json.dumps(
            {
                key: result.get(key)
                for key in (
                    "completed",
                    "fixture_removed",
                    "failure_stage",
                    "fixture_error",
                )
            }
        )
    )
    return int(not result["completed"] or not result["fixture_removed"])


if __name__ == "__main__":
    raise SystemExit(run_cases())


def test_postgres_deployment(monkeypatch, report_file, request):
    arguments = [__file__, "--output", str(report_file)]
    monkeypatch.setattr("sys.argv", arguments)
    assert run_cases() in (None, 0)


pytestmark = [pytest.mark.kubernetes]
