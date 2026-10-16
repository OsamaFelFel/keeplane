"""Owned Helm/PG namespace and deterministic host TLS edge; no preview mutation."""

import base64
import http.client
import json
import re
import secrets
import socket
import ssl
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from tests.support.kind_images import pin_loaded_image

POSTGRES = (
    "postgres@sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea"
)


class Edge(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def request(self):
        selected = self.server.selected
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.ports[selected], timeout=15
        )
        try:
            length = int(self.headers.get("Content-Length", "0"))
            assert 0 <= length <= 65536
            connection.request(
                self.command,
                self.path,
                self.rfile.read(length),
                {**dict(self.headers), "Connection": "close"},
            )
            response = connection.getresponse()
            payload = response.read(1024 * 1024 + 1)
            assert len(payload) <= 1024 * 1024
            self.server.observations.append(
                {
                    "copy": selected,
                    "path": urlsplit(self.path).path,
                    "status": response.status,
                }
            )
            self.send_response(response.status)
            for name, value in response.getheaders():
                if name.lower() not in (
                    "connection",
                    "transfer-encoding",
                    "content-length",
                ):
                    self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        finally:
            connection.close()

    do_GET = do_POST = do_DELETE = request


class HelmSignIn:
    def __init__(self, directory, source, image, image_id, kubeconfig, context, helm):
        self.directory, self.source = directory, source
        self.image, self.image_id = image, image_id
        self.kubeconfig, self.context, self.helm = kubeconfig, context, helm
        self.namespace = "keeplane-cli-auth-" + uuid.uuid4().hex[:10]
        self.processes, self.created = [], False
        self.operator_steps = 0
        self.serving = False
        self.edge = ThreadingHTTPServer(("127.0.0.1", 0), Edge)
        self.edge.selected, self.edge.ports, self.edge.observations = 0, [], []
        self.origin = "https://127.0.0.1:" + str(self.edge.server_port)
        self.password = secrets.token_urlsafe(32)
        self.report = {
            "completed": False,
            "cleaned": False,
            "namespace": self.namespace,
            "source_head": self.run("git", "rev-parse", "HEAD", cwd=source)
            .stdout.decode()
            .strip(),
            "app_image_id": image_id,
            "postgres_image": POSTGRES,
            "scope": "Auth only: host verified TLS relay and pod-specific port-forwards; no ingress, load-balancer, gateway coding or database HA claim.",
        }

    def run(self, *args, input_data=None, timeout=120, check=True, cwd=None):
        self.operator_steps += 1
        stem = self.directory / ("operator-" + str(self.operator_steps).zfill(3))
        try:
            process = subprocess.run(
                args,
                input=input_data,
                capture_output=True,
                timeout=timeout,
                cwd=cwd or self.source,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            for suffix, raw in (("stdout", error.stdout), ("stderr", error.stderr)):
                path = stem.with_suffix("." + suffix)
                path.write_bytes(raw or b"")
                path.chmod(0o600)
            raise RuntimeError("A bounded fixture operator command timed out") from None
        for suffix, raw in (("stdout", process.stdout), ("stderr", process.stderr)):
            path = stem.with_suffix("." + suffix)
            path.write_bytes(raw)
            path.chmod(0o600)
        if check and process.returncode:
            raise RuntimeError(
                "A fixture operator command failed; private diagnostics required"
            )
        return process

    def kube(self, *args, **kwargs):
        return self.run(
            "kubectl",
            "--kubeconfig",
            self.kubeconfig,
            "--context",
            self.context,
            "-n",
            self.namespace,
            *args,
            **kwargs,
        )

    def apply(self, value):
        return self.kube("apply", "-f", "-", input_data=json.dumps(value).encode())

    def secret(self, name, values):
        self.apply(
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

    def sql(self, statement, database="keeplane"):
        return (
            self.kube(
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

    def certificates(self):
        def openssl(*args):
            self.run("openssl", *args, cwd=self.directory, timeout=15)

        openssl(
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "2",
            "-subj",
            "/CN=Keeplane test CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
            "-keyout",
            "ca.key",
            "-out",
            "ca.crt",
        )
        for name, san in (("db", "DNS:db"), ("edge", "IP:127.0.0.1")):
            openssl(
                "req",
                "-new",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-subj",
                "/CN=" + name,
                "-keyout",
                name + ".key",
                "-out",
                name + ".csr",
            )
            (self.directory / (name + ".ext")).write_text(
                "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectAltName="
                + san
                + "\n"
            )
            openssl(
                "x509",
                "-req",
                "-in",
                name + ".csr",
                "-CA",
                "ca.crt",
                "-CAkey",
                "ca.key",
                "-CAcreateserial",
                "-days",
                "2",
                "-extfile",
                name + ".ext",
                "-out",
                name + ".crt",
            )
        self.ca = self.directory / "ca.crt"
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(
            self.directory / "edge.crt", self.directory / "edge.key"
        )
        self.edge.socket = context.wrap_socket(self.edge.socket, server_side=True)

    def service(self, name, port):
        self.apply(
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": name},
                "spec": {
                    "selector": {"app": name},
                    "ports": [{"port": port, "targetPort": port}],
                },
            }
        )

    def deployment(self, name, container, volumes=None, security=None):
        self.apply(
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": name},
                "spec": {
                    "replicas": 1,
                    "selector": {"matchLabels": {"app": name}},
                    "template": {
                        "metadata": {"labels": {"app": name}},
                        "spec": {
                            "automountServiceAccountToken": False,
                            "securityContext": security or {},
                            "volumes": volumes or [],
                            "containers": [container],
                        },
                    },
                },
            }
        )
        self.kube("rollout", "status", "deploy/" + name, "--timeout=90s")

    def install(self):
        assert (
            self.run(
                "kubectl", "--kubeconfig", self.kubeconfig, "config", "current-context"
            )
            .stdout.decode()
            .strip()
            == self.context
        )
        assert self.context == "kind-keeplane-netpol", "Use the isolated test cluster"
        assert re.fullmatch(r"sha256:[a-f0-9]{64}", self.image_id)
        assert (
            self.run("docker", "image", "inspect", self.image, "--format", "{{.Id}}")
            .stdout.decode()
            .strip()
            == self.image_id
        )
        self.run(
            "kind", "load", "docker-image", self.image, "--name", "keeplane-netpol"
        )
        pinned = pin_loaded_image(
            self.run, "docker.io/library/" + self.image, "keeplane-netpol"
        )
        self.report["app_manifest_reference"] = pinned
        self.created = True
        self.kube(
            "create",
            "-f",
            "-",
            input_data=json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {
                        "name": self.namespace,
                        "labels": {"keeplane-test-owner": self.namespace},
                    },
                }
            ).encode(),
        )
        self.certificates()
        app_password, ddl_password = (
            secrets.token_urlsafe(32),
            secrets.token_urlsafe(32),
        )
        self.secret("app-db", {"password": app_password})
        self.secret("ddl-db", {"password": ddl_password})
        self.secret(
            "identity",
            {
                "signing-secret": secrets.token_urlsafe(48),
                "first-admin-password": self.password,
            },
        )
        self.secret("database-ca", {"ca.crt": self.ca.read_bytes()})
        self.secret(
            "db-tls",
            {
                "tls.crt": (self.directory / "db.crt").read_bytes(),
                "tls.key": (self.directory / "db.key").read_bytes(),
            },
        )
        self.secret(
            "gateway-keys",
            {
                "runtime-key": secrets.token_urlsafe(32),
                "admin-key": secrets.token_urlsafe(32),
            },
        )
        self.secret("db-admin", {"password": secrets.token_urlsafe(32)})
        self.apply(
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": "db-hba"},
                "data": {
                    "pg_hba.conf": "local all all trust\nhostnossl all all 0.0.0.0/0 reject\nhostssl all all 0.0.0.0/0 scram-sha-256\n"
                },
            }
        )
        self.deployment(
            "db",
            {
                "name": "postgres",
                "image": POSTGRES,
                "imagePullPolicy": "Never",
                "args": [
                    "postgres",
                    "-c",
                    "ssl=on",
                    "-c",
                    "ssl_cert_file=/tls/tls.crt",
                    "-c",
                    "ssl_key_file=/tls/tls.key",
                    "-c",
                    "hba_file=/hba/pg_hba.conf",
                ],
                "env": [
                    {
                        "name": "POSTGRES_PASSWORD",
                        "valueFrom": {
                            "secretKeyRef": {"name": "db-admin", "key": "password"}
                        },
                    }
                ],
                "readinessProbe": {
                    "exec": {"command": ["pg_isready", "-U", "postgres"]},
                    "periodSeconds": 2,
                },
                "volumeMounts": [
                    {"name": "tls", "mountPath": "/tls", "readOnly": True},
                    {"name": "hba", "mountPath": "/hba", "readOnly": True},
                ],
            },
            [
                {
                    "name": "tls",
                    "secret": {"secretName": "db-tls", "defaultMode": 0o640},
                },
                {"name": "hba", "configMap": {"name": "db-hba"}},
            ],
            {"fsGroup": 70},
        )
        self.service("db", 5432)
        self.sql(
            "CREATE ROLE keeplane_migrate LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD '"
            + ddl_password
            + "'; CREATE ROLE keeplane_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD '"
            + app_password
            + "'; CREATE DATABASE keeplane OWNER keeplane_migrate; REVOKE ALL ON DATABASE keeplane FROM PUBLIC; GRANT CONNECT ON DATABASE keeplane TO keeplane_app;",
            "postgres",
        )
        self.sql(
            "REVOKE CREATE ON SCHEMA public FROM PUBLIC; GRANT USAGE ON SCHEMA public TO keeplane_app; ALTER DEFAULT PRIVILEGES FOR ROLE keeplane_migrate IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO keeplane_app; ALTER DEFAULT PRIVILEGES FOR ROLE keeplane_migrate IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO keeplane_app;"
        )
        self.apply(
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
        self.apply(
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": "gateway-fixture"},
                "data": {
                    "fixture.py": (
                        self.source / "tests/fixtures/postgres_gateway.py"
                    ).read_text()
                },
            }
        )
        self.deployment(
            "gateway-fixture",
            {
                "name": "fixture",
                "image": pinned,
                "imagePullPolicy": "Never",
                "command": ["python", "/fixture/fixture.py"],
                "volumeMounts": [
                    {"name": "script", "mountPath": "/fixture", "readOnly": True}
                ],
            },
            [{"name": "script", "configMap": {"name": "gateway-fixture"}}],
        )
        self.service("gateway-fixture", 4000)
        self.values = {
            "app": {
                "image": pinned,
                "pullPolicy": "Never",
                "replicaCount": 2,
                "cliSignIn": {"enabled": True},
                "postgres": {
                    "enabled": True,
                    "host": "db",
                    "database": "keeplane",
                    "user": "keeplane_app",
                    "credentialsSecret": "app-db",
                    "identitySecret": "identity",
                    "caSecret": "database-ca",
                    "providerKeysClaim": "provider-keys",
                    "publicOrigin": self.origin,
                    "migration": {
                        "user": "keeplane_migrate",
                        "credentialsSecret": "ddl-db",
                    },
                },
            },
            "gateway": {
                "mode": "existing",
                "install": False,
                "url": "http://gateway-fixture:4000",
                "expectedVersion": "postgres-test-fixture",
                "keysSecret": "gateway-keys",
            },
        }
        self.chart()
        self.pods = sorted(
            row["metadata"]["name"]
            for row in json.loads(
                self.kube("get", "pods", "-l", "app=trial-app", "-o", "json").stdout
            )["items"]
        )
        assert len(self.pods) == 2
        serving = json.loads(
            self.kube("get", "pods", "-l", "app=trial-app", "-o", "json").stdout
        )["items"]
        assert all(
            row["spec"]["containers"][0]["image"] == pinned
            and row["status"]["containerStatuses"][0]["ready"]
            for row in serving
        )
        self.report["app_pod_uids"] = [row["metadata"]["uid"] for row in serving]
        self.edge.ports = [self.forward(pod) for pod in self.pods]
        threading.Thread(target=self.edge.serve_forever, daemon=True).start()
        self.serving = True
        self.report["pod_names"] = self.pods

    def app_script(self, script, *, check=True):
        return self.kube(
            "exec",
            "-i",
            "pod/" + self.pods[0],
            "--",
            "python",
            "-",
            check=check,
            input_data=(
                "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');django.setup()\n"
                + script
            ).encode(),
        )

    def external_registration(self):
        # The chart's external-migration mode creates no migration Job. This
        # explicit operator action uses the same reviewed image, roles and commands.
        rendered = self.run(
            self.helm,
            "template",
            "trial",
            str(self.source / "deploy/helm/keeplane"),
            "-n",
            self.namespace,
            "-f",
            str(self.directory / "values.json"),
            "--set",
            "app.postgres.migration.enabled=true",
            "--show-only",
            "templates/postgres-migrate.yaml",
        ).stdout
        value = json.loads(
            self.kube(
                "create",
                "--dry-run=client",
                "-f",
                "-",
                "-o",
                "json",
                input_data=rendered,
            ).stdout
        )
        value["metadata"] = {"name": "explicit-operator-registration"}
        self.apply(value)
        self.kube(
            "wait",
            "--for=condition=complete",
            "job/explicit-operator-registration",
            "--timeout=90s",
        )

    def logs(self):
        return b"\n".join(self.kube("logs", "pod/" + pod).stdout for pod in self.pods)

    def failure_diagnostics(self):
        # Never print Kubernetes output: even access logs can contain OAuth codes.
        try:
            pods = json.loads(
                self.kube("get", "pods", "-o", "json", timeout=10).stdout
            )["items"]
            for row in pods:
                for container in (
                    row["spec"].get("initContainers", []) + row["spec"]["containers"]
                ):
                    self.kube(
                        "logs",
                        row["metadata"]["name"],
                        "-c",
                        container["name"],
                        "--tail=100",
                        timeout=5,
                        check=False,
                    )
        except (RuntimeError, ValueError, KeyError):
            pass  # The original failure and any successful private captures remain.

    def chart(self, upgrade=False):
        path = self.directory / "values.json"
        path.write_text(json.dumps(self.values))
        self.run(
            self.helm,
            "--kubeconfig",
            self.kubeconfig,
            "--kube-context",
            self.context,
            "upgrade" if upgrade else "install",
            "trial",
            str(self.source / "deploy/helm/keeplane"),
            "--namespace",
            self.namespace,
            "-f",
            str(path),
            "--wait",
            "--timeout",
            "120s",
            timeout=150,
        )

    def forward(self, pod):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen(
            [
                "kubectl",
                "--kubeconfig",
                self.kubeconfig,
                "--context",
                self.context,
                "-n",
                self.namespace,
                "port-forward",
                "pod/" + pod,
                str(port) + ":3000",
                "--address=127.0.0.1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.processes.append(process)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return port
            except OSError:
                assert process.poll() is None, "Owned port-forward stopped"
                time.sleep(0.1)
        raise RuntimeError("Owned port-forward did not become ready")

    def route(self, index):
        assert index in (0, 1)
        self.edge.selected = index

    def close(self):
        if self.serving:
            self.edge.shutdown()
        self.edge.server_close()
        for process in self.processes:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if self.created:
            assert re.fullmatch(r"keeplane-cli-auth-[a-f0-9]{10}", self.namespace)
            existing = self.kube(
                "get", "namespace", self.namespace, "--ignore-not-found", "-o", "json"
            ).stdout
            if not existing:
                self.report["cleaned"] = True
                return
            assert (
                json.loads(existing)["metadata"]["labels"].get("keeplane-test-owner")
                == self.namespace
            )
            volumes = json.loads(self.kube("get", "pv", "-o", "json").stdout)["items"]
            owned = [
                item["metadata"]["name"]
                for item in volumes
                if item["spec"].get("claimRef", {}).get("namespace") == self.namespace
            ]
            self.kube(
                "delete", "namespace", self.namespace, "--wait=true", "--timeout=90s"
            )
            assert (
                self.kube(
                    "get",
                    "namespace",
                    self.namespace,
                    "--ignore-not-found",
                    "-o",
                    "name",
                ).stdout
                == b""
            )
            for name in owned:
                self.kube("wait", "--for=delete", "pv/" + name, "--timeout=60s")
        self.report["cleaned"] = True
