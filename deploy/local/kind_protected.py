"""Install the protected developer release on the local kind cluster.

`deploy/local/kind-up.sh` runs this with KEEPLANE_KIND_PROTECTED=on, after the
SQLite trial is installed. It adds a second Keeplane release, `keeplane` in
namespace `keeplane-protected`, with the chart's own options
(`protected-values.yaml`): PostgreSQL accounts with CLI sign-in
(app.postgres, app.cliSignIn), the managed gateway with the model enroller and
its database roles on both copies (gateway.enroller), and one public HTTPS
address, https://keeplane.kind.test, through an ingress controller, for the
web UI, the CLI and protected model calls. The namespace starts fresh on every
run.

Everything it installs is a disposable fixture: a PostgreSQL account database
that accepts only TLS with a test certificate, the gateway database, the HTTPS
fixture provider (`cloud-provider-fixture.yaml`) and ingress-nginx. Inside the
cluster the name api.openai.com points to that fixture provider, so OpenAI
models added to this release reach only the fixture. A new test CA signs the
database's, the public address's and the fixture's certificates; its private
key is deleted once it has signed. The CA certificate stays in
<runtime>/kind-protected/ca.pem for the CLI and the tests.

    python3 deploy/local/kind_protected.py check
    python3 deploy/local/kind_protected.py install

See docs/guide/kubernetes-local.md, "Try the protected developer path".
"""

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLUSTER = "keeplane"
# The only Kubernetes context this script changes: kind's name for the cluster.
CONTEXT = "kind-" + CLUSTER
NODE = CLUSTER + "-control-plane"
NAMESPACE = "keeplane-protected"
RELEASE = "keeplane"
HOST = "keeplane.kind.test"
PUBLIC_URL = "https://" + HOST
# The fixture provider answers for this name inside the cluster.
PROVIDER_HOST = "api.openai.com"
IMAGE = "keeplane-protected:kind-local"
IMAGE_TARGET = "postgres-cli-auth-trial"
LOADED_IMAGE = "docker.io/library/" + IMAGE
# ingress-nginx (Apache-2.0), as the isolated-network CI job pins it: its kind
# manifest names every image by digest.
INGRESS_NGINX_VERSION = "controller-v1.15.1"
INGRESS_NGINX_URL = (
    "https://raw.githubusercontent.com/kubernetes/ingress-nginx/"
    + INGRESS_NGINX_VERSION
    + "/deploy/static/provider/kind/deploy.yaml"
)
INGRESS_NGINX_SHA256 = (
    "2a3ae008c8786431115502644e77ab398fdebfb721a5d1195ed3089cde3299df"
)
# One status role per gateway copy, in copy order (protected-values.yaml).
STATUS_ROLES = ("keeplane_status_0", "keeplane_status_1")
MARK = "# keeplane-kind-protected"
HOSTS_MISSING = (
    f"{HOST} must point to this computer for the protected release. Add this "
    f"line to /etc/hosts and run again:\n127.0.0.1 {HOST}"
)
TLS_CONFIG = """[req]
distinguished_name = name
prompt = no
[name]
CN = {name}
[ca]
basicConstraints = critical,CA:TRUE
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
[leaf]
subjectAltName = {names}
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
"""
# Each certificate the test CA signs: its file stem and the names it holds.
CERTIFICATES = {
    "db": ("DNS:db",),
    "public": ("DNS:" + HOST,),
    "provider": ("DNS:" + PROVIDER_HOST, "DNS:cloud-provider"),
}


def roles_sql(passwords):
    """The database operator's role setup, as postgres-accounts.md and
    guard-status-roles.md describe it, for a fresh server."""
    create = "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD '{}';"
    read_only = "ALTER ROLE {} SET default_transaction_read_only = on;"
    lines = [
        create.format("keeplane_migrate", passwords["migration"]),
        create.format("keeplane_app", passwords["app"]),
        create.format("keeplane_enroller", passwords["enroller"]),
        read_only.format("keeplane_enroller"),
    ]
    for index, role in enumerate(STATUS_ROLES):
        lines += [
            create.format(role, passwords[f"status-{index}"]),
            read_only.format(role),
        ]
    connecting = ", ".join(("keeplane_app", "keeplane_enroller", *STATUS_ROLES))
    lines += [
        "CREATE DATABASE keeplane OWNER keeplane_migrate;",
        "REVOKE ALL ON DATABASE keeplane FROM PUBLIC;",
        f"GRANT CONNECT ON DATABASE keeplane TO {connecting};",
    ]
    for password in passwords.values():
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,}", password):
            raise ValueError("Each database password must be URL-safe text")
    return "\n".join(lines) + "\n"


SCHEMA_SQL = """REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO keeplane_app;
ALTER DEFAULT PRIVILEGES FOR ROLE keeplane_migrate IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO keeplane_app;
ALTER DEFAULT PRIVILEGES FOR ROLE keeplane_migrate IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO keeplane_app;
"""


def with_provider_host(corefile, address):
    """The cluster DNS settings with PROVIDER_HOST pointing to `address`.

    A block this script added earlier is replaced; any other `hosts` block is
    refused, so an installer's own settings are never changed.
    """
    if not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", address):
        raise ValueError("The fixture provider has no cluster address")
    kept = re.sub(
        r"\n[ \t]*" + re.escape(MARK) + r"[^\n]*\n[ \t]*hosts \{[^}]*\}", "", corefile
    )
    if re.search(r"^\s*hosts\b", kept, re.MULTILINE):
        raise ValueError("The cluster DNS already has a hosts block; leave it as it is")
    lines = kept.split("\n")
    ready = next(
        (number for number, line in enumerate(lines) if line.strip() == "ready"), None
    )
    if ready is None:
        raise ValueError("The cluster DNS settings are not kind's defaults")
    block = [
        f"    {MARK}: the protected release's fixture provider",
        "    hosts {",
        f"        {address} {PROVIDER_HOST}",
        "        fallthrough",
        "    }",
    ]
    return "\n".join(lines[: ready + 1] + block + lines[ready + 1 :])


def context_refusal(context, expected=CONTEXT):
    """Why this script won't change the cluster in `context`, or None for kind's.

    It deletes a namespace and changes the cluster DNS, so it never runs
    against any cluster but the local kind one (or, for the isolated-network
    run, that run's kind cluster), whatever the kubeconfig says.
    """
    if context == expected:
        return None
    return (
        f"Refusing Kubernetes context {context!r}: the protected release installs "
        f"only on the local kind cluster ({expected}). Check KEEPLANE_KUBECONFIG."
    )


def resolves_here(host=HOST):
    try:
        found = {row[4][0] for row in socket.getaddrinfo(host, 443)}
    except OSError:
        return False
    return bool(found) and found <= {"127.0.0.1", "::1"}


class Installer:
    """The install steps. tests/fixtures/isolated-network/protected.py
    reuses them on the isolated kind network, with its own cluster, address,
    certificates, image, provider and values."""

    context = CONTEXT
    public_url = PUBLIC_URL
    values = ("deploy/local/protected-values.yaml",)

    def __init__(self, kubeconfig, runtime, helm):
        self.kubeconfig, self.runtime, self.helm = kubeconfig, Path(runtime), helm
        self.state = self.runtime / "kind-protected"

    def run(self, *command, data=None, timeout=300, check=True):
        result = subprocess.run(
            command,
            input=data,
            capture_output=True,
            timeout=timeout,
            check=False,
            cwd=ROOT,
        )
        if check and result.returncode:
            # Command output can hold a Secret's name but never its value:
            # every Secret goes to kubectl on standard input.
            message = result.stderr.decode(errors="replace").strip().splitlines()
            raise SystemExit(
                f"{command[0]} {command[1] if len(command) > 1 else ''} failed: "
                + (message[-1] if message else "no message")
            )
        return result

    def kubectl(self, *arguments, **options):
        return self.run(
            "kubectl", "--kubeconfig", self.kubeconfig, *arguments, **options
        )

    def kube(self, *arguments, **options):
        return self.kubectl("-n", NAMESPACE, *arguments, **options)

    def apply(self, document):
        self.kube("apply", "-f", "-", data=json.dumps(document).encode())

    def secret(self, name, values, kind="Opaque"):
        self.apply(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": name},
                "type": kind,
                "data": {
                    key: base64.b64encode(value).decode()
                    for key, value in values.items()
                },
            }
        )

    def configmap(self, name, values):
        self.apply(
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": name},
                "data": values,
            }
        )

    def private(self, name, make):
        """A private file in the state folder, made once."""
        path = self.state / name
        if not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                stream.write(make())
        return path.read_text().strip()

    def credentials(self):
        self.state.mkdir(mode=0o700, exist_ok=True)
        self.state.chmod(0o700)

        def token():
            return secrets.token_urlsafe(32)

        passwords = {
            name: self.private(f"{name}-db-password", token)
            for name in ("app", "migration", "enroller", "admin")
        }
        for index in range(len(STATUS_ROLES)):
            passwords[f"status-{index}"] = self.private(
                f"status-{index}-db-password", token
            )
        self.passwords = passwords
        self.signing = self.private("signing-secret", lambda: secrets.token_urlsafe(48))
        self.callback = self.private("callback-key", token)

    def certificates(self):
        """A new test CA and the three certificates it signs; then its key is gone."""
        with tempfile.TemporaryDirectory(prefix="keeplane-kind-protected-") as work:
            work = Path(work)

            def openssl(*arguments):
                self.run("openssl", *arguments, timeout=60)

            (work / "ca.cnf").write_text(
                TLS_CONFIG.format(name="Keeplane kind protected test CA", names="")
            )
            openssl(
                "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256",
                "-keyout", str(work / "ca.key"), "-out", str(work / "ca.pem"),
                "-days", "30", "-config", str(work / "ca.cnf"), "-extensions", "ca",
            )  # fmt: skip
            for stem, names in CERTIFICATES.items():
                config = work / f"{stem}.cnf"
                config.write_text(
                    TLS_CONFIG.format(name=names[0][4:], names=",".join(names))
                )
                openssl(
                    "req", "-new", "-newkey", "rsa:2048", "-nodes", "-sha256",
                    "-keyout", str(work / f"{stem}.key"), "-out", str(work / f"{stem}.csr"),
                    "-config", str(config),
                )  # fmt: skip
                openssl(
                    "x509", "-req", "-in", str(work / f"{stem}.csr"),
                    "-CA", str(work / "ca.pem"), "-CAkey", str(work / "ca.key"),
                    "-CAcreateserial", "-out", str(work / f"{stem}.pem"),
                    "-days", "30", "-sha256", "-extfile", str(config), "-extensions", "leaf",
                )  # fmt: skip
            self.tls = {
                name: (work / name).read_bytes()
                for name in ["ca.pem"]
                + [f"{stem}.{kind}" for stem in CERTIFICATES for kind in ("pem", "key")]
            }
        ca = self.state / "ca.pem"
        ca.write_bytes(self.tls["ca.pem"])
        ca.chmod(0o644)

    def image(self):
        self.run(
            "docker", "build", "-f", "components/control-plane/Dockerfile",
            "--target", IMAGE_TARGET, "-t", IMAGE, ".", timeout=1800,
        )  # fmt: skip
        self.run("kind", "load", "docker-image", IMAGE, "--name", CLUSTER, timeout=600)
        listed = self.run(
            "docker", "exec", NODE, "ctr", "-n", "k8s.io", "images", "list",
            "name==" + LOADED_IMAGE,
        ).stdout.decode().splitlines()  # fmt: skip
        fields = listed[1].split() if len(listed) == 2 else []
        if len(fields) < 3 or not re.fullmatch(r"sha256:[0-9a-f]{64}", fields[2]):
            raise SystemExit("The loaded app image has no manifest digest on the node")
        pinned = LOADED_IMAGE.rsplit(":", 1)[0] + "@" + fields[2]
        self.run(
            "docker", "exec", NODE, "ctr", "-n", "k8s.io", "images", "tag", "--force",
            LOADED_IMAGE, pinned,
        )  # fmt: skip
        self.pinned = pinned

    def fresh_namespace(self):
        existing = self.kubectl(
            "get", "namespace", NAMESPACE, "--ignore-not-found", "-o", "name"
        ).stdout.strip()
        if existing:
            self.kubectl(
                "delete", "namespace", NAMESPACE, "--wait=true", "--timeout=300s",
                timeout=330,
            )  # fmt: skip
        self.kubectl("create", "namespace", NAMESPACE)

    def fixtures(self):
        self.release_fixtures()
        self.provider_fixture()
        for deployment in ("db", "postgres"):
            self.kube(
                "rollout", "status", f"deployment/{deployment}", "--timeout=240s",
                timeout=260,
            )  # fmt: skip

    def release_fixtures(self):
        """The release's Secrets, its account and gateway databases."""
        runtime = self.runtime
        first_admin = (runtime / "first-admin-password").read_bytes()
        keys = {
            name: (runtime / f"gateway-{name}").read_bytes()
            for name in (
                "runtime-key",
                "admin-key",
                "runtime-key-hash",
                "admin-key-hash",
            )
        }
        tls = self.tls
        self.secret("db-admin", {"password": self.passwords["admin"].encode()})
        self.secret("db-tls", {"tls.crt": tls["db.pem"], "tls.key": tls["db.key"]})
        self.secret("keeplane-app-db", {"password": self.passwords["app"].encode()})
        self.secret(
            "keeplane-migration-db", {"password": self.passwords["migration"].encode()}
        )
        self.secret(
            "keeplane-identity",
            {
                "signing-secret": self.signing.encode(),
                "first-admin-password": first_admin,
            },
        )
        self.secret("keeplane-database-ca", {"ca.crt": tls["ca.pem"]})
        self.secret(
            "keeplane-enroller-db", {"password": self.passwords["enroller"].encode()}
        )
        self.secret(
            "keeplane-guard-status-db",
            {
                f"copy-{index}-password": self.passwords[f"status-{index}"].encode()
                for index in range(len(STATUS_ROLES))
            },
        )
        self.secret(
            "keeplane-gateway-keys", {**keys, "callback-key": self.callback.encode()}
        )
        self.secret(
            "keeplane-gateway-db",
            {"password": (runtime / "gateway-db-password").read_bytes()},
        )
        self.secret(
            "keeplane-tls",
            {"tls.crt": tls["public.pem"], "tls.key": tls["public.key"]},
            kind="kubernetes.io/tls",
        )
        self.apply(
            {
                "apiVersion": "v1",
                "kind": "PersistentVolumeClaim",
                "metadata": {"name": "keeplane-provider-keys"},
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "resources": {"requests": {"storage": "1Gi"}},
                },
            }
        )
        for manifest in ("accounts-db-fixture.yaml", "postgres-fixture.yaml"):
            self.kube("apply", "-f", str(ROOT / "deploy/local" / manifest))

    def provider_fixture(self):
        """The HTTPS fixture provider in the namespace, and its CA for the release."""
        tls = self.tls
        self.secret(
            "cloud-provider-key",
            {"key": (self.runtime / "cloud-provider-key").read_bytes()},
        )
        self.secret(
            "cloud-provider-tls",
            {
                "provider.pem": tls["provider.pem"],
                "provider.key": tls["provider.key"],
                "ca.pem": tls["ca.pem"],
            },
        )
        self.configmap("cloud-provider-ca", {"ca.crt": tls["ca.pem"].decode()})
        self.configmap(
            "cloud-provider-fixture",
            {
                "cloud_provider.py": (
                    ROOT / "tests/fixtures/cloud_provider.py"
                ).read_text()
            },
        )
        self.kube("apply", "-f", str(ROOT / "deploy/local/cloud-provider-fixture.yaml"))
        self.kube(
            "rollout", "status", "deployment/cloud-provider", "--timeout=240s",
            timeout=260,
        )  # fmt: skip

    def sql(self, statements, database):
        self.kube(
            "exec", "-i", "deploy/db", "--", "psql", "-X", "-q", "-v", "ON_ERROR_STOP=1",
            "-U", "postgres", "-d", database, data=statements.encode(), timeout=120,
        )  # fmt: skip

    def roles(self):
        roles = dict(self.passwords)
        roles.pop("admin")
        self.sql(roles_sql(roles), "postgres")
        self.sql(SCHEMA_SQL, "keeplane")

    def provider_address(self):
        """The address the cluster DNS gives PROVIDER_HOST."""
        return json.loads(
            self.kube("get", "service", "cloud-provider", "-o", "json").stdout
        )["spec"]["clusterIP"]

    def provider_dns(self):
        address = self.provider_address()
        dns = json.loads(
            self.kubectl(
                "-n", "kube-system", "get", "configmap", "coredns", "-o", "json"
            ).stdout
        )
        corefile = with_provider_host(dns["data"]["Corefile"], address)
        self.kubectl(
            "-n", "kube-system", "patch", "configmap", "coredns", "--type", "merge",
            "--patch", json.dumps({"data": {"Corefile": corefile}}),
        )  # fmt: skip
        self.kubectl("-n", "kube-system", "rollout", "restart", "deployment/coredns")
        self.kubectl(
            "-n", "kube-system", "rollout", "status", "deployment/coredns",
            "--timeout=180s", timeout=200,
        )  # fmt: skip

    def ingress_controller(self):
        manifest = self.state / "ingress-nginx.yaml"
        if (
            not manifest.is_file()
            or hashlib.sha256(manifest.read_bytes()).hexdigest() != INGRESS_NGINX_SHA256
        ):
            with urllib.request.urlopen(INGRESS_NGINX_URL, timeout=60) as response:
                body = response.read(4 * 1024 * 1024)
            if hashlib.sha256(body).hexdigest() != INGRESS_NGINX_SHA256:
                raise SystemExit(
                    "The ingress controller manifest checksum does not match"
                )
            manifest.write_bytes(body)
        self.kubectl("apply", "-f", str(manifest))
        self.kubectl(
            "-n", "ingress-nginx", "rollout", "status",
            "deployment/ingress-nginx-controller", "--timeout=300s", timeout=320,
        )  # fmt: skip
        # The admission jobs delete themselves; the webhook works once its CA
        # bundle is patched in.
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            bundle = self.kubectl(
                "get", "validatingwebhookconfiguration", "ingress-nginx-admission",
                "-o", "jsonpath={.webhooks[0].clientConfig.caBundle}", check=False,
            ).stdout.strip()  # fmt: skip
            if bundle:
                return
            time.sleep(3)
        raise SystemExit(
            "The ingress controller's admission webhook never got its CA bundle"
        )

    def chart(self):
        values = [option for path in self.values for option in ("-f", path)]
        self.run(
            self.helm, "upgrade", "--install", RELEASE, "deploy/helm/keeplane",
            "--kubeconfig", self.kubeconfig, "--namespace", NAMESPACE, *values,
            "--set", "app.image=" + self.pinned, "--wait", "--timeout", "480s",
            timeout=540,
        )  # fmt: skip

    def wait_ready(self):
        context = ssl.create_default_context(cafile=str(self.state / "ca.pem"))
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=context),
        )
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                with opener.open(
                    self.public_url + "/health/ready", timeout=10
                ) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(3)
        raise SystemExit(f"{self.public_url} did not become ready")

    def own_cluster(self):
        context = self.kubectl("config", "current-context", check=False)
        refusal = context_refusal(context.stdout.decode().strip(), self.context)
        if refusal:
            raise SystemExit(refusal)

    def install(self):
        # Before anything changes: the namespace reset and the cluster DNS
        # change below are for the local kind cluster only.
        self.own_cluster()
        self.credentials()
        self.certificates()
        self.image()
        self.fresh_namespace()
        self.fixtures()
        self.roles()
        self.provider_dns()
        self.ingress_controller()
        self.chart()
        self.wait_ready()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("check", "install"))
    arguments = parser.parse_args(argv)
    if not resolves_here():
        print(HOSTS_MISSING, file=sys.stderr)
        return 1
    if arguments.action == "check":
        return 0
    installer = Installer(
        os.environ["KEEPLANE_KUBECONFIG"],
        os.environ["KEEPLANE_RUNTIME_DIR"],
        os.environ.get("KEEPLANE_HELM_BIN", "helm"),
    )
    installer.install()
    print(
        f"Keeplane protected developer release: {PUBLIC_URL} "
        f"(test CA: {installer.state / 'ca.pem'})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
