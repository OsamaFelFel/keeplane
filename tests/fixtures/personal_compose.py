"""Owned synthetic TLS provider for the actual managed installer and CLI."""

import json
import secrets
import subprocess
import uuid
from http.cookies import SimpleCookie
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from tests.fixtures.managed_compose import OwnedCompose


class PersonalCompose(OwnedCompose):
    def __init__(
        self,
        source,
        directory,
        image,
        *,
        public_origin=None,
        provider_module="tests.fixtures.personal_provider",
        upstream_model="fixture-personal",
        include_shared=False,
    ):
        super().__init__(source, directory, image)
        self.public_origin = public_origin or self.server
        self.upstream_model, self.include_shared = upstream_model, include_shared
        self.keys = {label: secrets.token_urlsafe(32) for label in ("a", "b", "a_next")}
        self.keys["shared"] = self.values["provider-key"]
        self.models = {"openai": "personal-openai", "anthropic": "personal-anthropic"}
        self.cookies = {}
        self.opener = build_opener(ProxyHandler({}))
        tls = self.repo / "tls-input"
        tls.mkdir(mode=0o700)

        def openssl(*arguments):
            completed = subprocess.run(
                ["openssl", *arguments],
                cwd=tls,
                capture_output=True,
                timeout=10,
                check=False,
            )
            if completed.returncode:
                raise RuntimeError("Owned provider certificate setup failed")

        openssl(
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            "ca.key",
            "-out",
            "ca.pem",
            "-days",
            "1",
            "-subj",
            "/CN=Keeplane fixture CA",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-addext", "subjectKeyIdentifier=hash",
        )
        openssl(
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            "provider.key",
            "-out",
            "provider.csr",
            "-subj",
            "/CN=model",
        )
        (tls / "extensions").write_text(
            "subjectAltName=DNS:model\nbasicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n"
            "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n"
        )
        openssl(
            "x509",
            "-req",
            "-in",
            "provider.csr",
            "-CA",
            "ca.pem",
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-out",
            "provider.pem",
            "-days",
            "1",
            "-sha256",
            "-extfile",
            "extensions",
        )
        (tls / "ca.pem").chmod(0o644)
        (tls / "expected.json").write_text(json.dumps(self.keys))
        (tls / "expected.json").chmod(0o600)
        base = json.loads(self.base.read_text())
        base["volumes"]["model-tls"] = {}
        initialize = base["services"]["initialize"]
        initialize["volumes"] += ["model-tls:/model-tls", "./tls-input:/host-tls:ro"]
        initialize["command"][-1] += (
            "\nroot=Path('/model-tls');root.chmod(0o700);os.chown(root,65532,65532)\n"
            "for name in ('provider.pem','provider.key','ca.pem','expected.json'):\n"
            " target=root/name;shutil.copyfile(Path('/host-tls')/name,target);"
            "target.chmod(0o600);os.chown(target,65532,65532)\n"
        )
        base["services"]["model"]["command"] = [
            "python",
            "-c",
            "from " + provider_module + " import PersonalProvider,serve;"
            "PersonalProvider.upstream_models={"
            + repr(upstream_model)
            + "};serve(PersonalProvider)",
        ]
        base["services"]["model"]["volumes"].append("model-tls:/model-tls:ro")
        for name in ("app", "gateway"):
            service = base["services"][name]
            service.setdefault("environment", {})["SSL_CERT_FILE"] = "/fixture-ca.pem"
            service["volumes"].append("./tls-input/ca.pem:/fixture-ca.pem:ro")
        base["services"]["app"]["environment"].update(
            PUBLIC_ORIGIN=self.public_origin,
            PREVIEW_OPENAI_BASE_URL="https://model:18080/v1",
            PREVIEW_ANTHROPIC_BASE_URL="https://model:18080/v1",
        )
        self.base.write_text(json.dumps(base))

    def admin(self, path, body=None, method=None):
        origin = self.public_origin

        def request(target, payload=None, verb=None, csrf=None):
            headers = {
                "Host": urlsplit(origin).netloc,
                "Origin": origin,
                "Cookie": "; ".join(
                    name + "=" + value for name, value in self.cookies.items()
                ),
            }
            if payload is not None:
                headers.update(
                    {"Content-Type": "application/json", "X-Keeplane-Action": "1"}
                )
            if csrf:
                headers["X-CSRFToken"] = csrf
            outgoing = Request(
                self.server + target,
                None if payload is None else json.dumps(payload).encode(),
                headers,
                method=verb,
            )
            try:
                with self.opener.open(outgoing, timeout=30) as response:
                    for raw in response.headers.get_all("Set-Cookie", []):
                        parsed = SimpleCookie()
                        parsed.load(raw)
                        self.cookies.update(
                            {name: value.value for name, value in parsed.items()}
                        )
                    return response.status, json.load(response)
            except HTTPError as error:
                status = error.code
                error.close()
                return status, None

        status, options = request("/api/auth-options")
        if status != 200:
            raise RuntimeError("Owned administration CSRF setup failed")
        return request(path, body, method, options["csrf_token"])

    def bootstrap(self):
        """Real admin/model APIs and actual launcher; no provider key admission."""
        self.validate()
        self.compose("run", "--rm", "--no-deps", "initialize")
        self.compose("run", "--rm", "--no-deps", "runtime-init")
        self.compose(
            "up", "-d", "--no-build", "--pull", "never", "--no-deps", "gateway", "model"
        )
        self.compose(
            "run",
            "--rm",
            "--no-deps",
            "runtime-install",
            "python",
            "manage.py",
            "migrate",
            "--noinput",
        )
        self.compose("up", "-d", "--no-build", "--pull", "never", "--no-deps", "app")
        self.ready()
        assert (
            self.admin(
                "/api/session",
                {
                    "username": "first-admin",
                    "password": self.values["first-admin-password"],
                },
            )[0]
            == 200
        )
        assert self.admin("/api/data-classes/mode", {"enabled": True}, "PUT")[0] == 200
        accounts = {}
        for label in ("a", "b"):
            password = secrets.token_urlsafe(32)
            status, actor = self.admin(
                "/api/users",
                {
                    "username": "personal-" + label,
                    "password": password,
                    "role": "developer",
                },
            )
            assert status == 201
            accounts[label] = {**actor, "password": password}
        for provider, model in self.models.items():
            status, _ = self.admin(
                "/api/models",
                {
                    "name": model,
                    "model": self.upstream_model,
                    "source": provider,
                    "key_choice": "personal",
                    "approved_classes": ["Confidential"],
                },
            )
            assert status == 200
        if self.include_shared:
            self.models["shared"] = "shared"
            assert (
                self.admin(
                    "/api/models",
                    {
                        "name": "shared",
                        "model": self.upstream_model,
                        "source": "openai",
                        "key_choice": "shared",
                        "shared_key": self.keys["shared"],
                        "approved_classes": ["Confidential"],
                    },
                )[0]
                == 200
            )
        self.install(list(self.models.values()))
        # Fixture-only project seed. Actual CLI init still registers its use;
        # this does not claim a new project was created through the CLI.
        project = str(uuid.uuid4())
        seed_script = (
            "import os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');"
            "import django;django.setup();from projects.services import DjangoProjectStore;"
            "DjangoProjectStore().register_use("
            + repr(accounts["a"]["id"])
            + ","
            + repr(project)
            + ", 'Personal coding')"
        )
        self.compose("exec", "-T", "app", "python", "-c", seed_script)
        assert (
            self.admin(
                "/api/projects/" + project + "/class",
                {"class_id": "confidential"},
                "PUT",
            )[0]
            == 200
        )
        return {
            "server": self.public_origin,
            "project_id": project,
            "models": dict(self.models),
            "accounts": accounts,
            "synthetic_keys": {name: self.keys[name] for name in ("a", "b", "a_next")},
        }

    def provider_status(self):
        return json.loads(
            self.compose(
                "exec",
                "-T",
                "model",
                "python",
                "-c",
                "import ssl,urllib.request;print(urllib.request.urlopen('https://model:18080/fixture/status',"
                "context=ssl.create_default_context(cafile='/model-tls/ca.pem')).read().decode())",
            )
        )
