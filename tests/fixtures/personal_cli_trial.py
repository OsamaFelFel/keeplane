"""Owned installed Personal CLI acceptance; requires frozen source and artifacts."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def client_layer(owned, image, wheel, binary):
    """Add only a fixed TLS front and a separately isolated developer client."""
    root = owned.repo
    inputs = root / "client-files"
    inputs.mkdir(mode=0o700)
    for source, name in ((wheel, "keeplane.whl"), (binary, "opencode")):
        shutil.copyfile(source, inputs / name)
        (inputs / name).chmod(0o755 if name == "opencode" else 0o644)
    tls = root / "front-tls-input"
    tls.mkdir(mode=0o700)
    subprocess.run(
        [
            "openssl",
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(tls / "front.key"),
            "-out",
            str(tls / "front.csr"),
            "-subj",
            "/CN=front",
        ],
        capture_output=True,
        timeout=15,
        check=True,
    )
    (tls / "extensions").write_text(
        "subjectAltName=DNS:front\nbasicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
        "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n"
    )
    subprocess.run(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(tls / "front.csr"),
            "-CA",
            str(root / "tls-input/ca.pem"),
            "-CAkey",
            str(root / "tls-input/ca.key"),
            "-CAcreateserial",
            "-out",
            str(tls / "front.pem"),
            "-days",
            "1",
            "-sha256",
            "-extfile",
            str(tls / "extensions"),
        ],
        capture_output=True,
        timeout=15,
        check=True,
    )
    base = json.loads(owned.base.read_text())
    base["networks"]["developer"] = {"internal": True}
    base["volumes"]["front-tls"] = {}
    base["services"]["client-init"] = {
        "image": base["services"]["initialize"]["image"],
        "user": "0",
        "network_mode": "none",
        "command": [
            "python",
            "-c",
            """import os,shutil
from pathlib import Path
root=Path('/front-tls');root.chmod(0o700);os.chown(root,65532,65532)
for name in ('front.pem','front.key'):
 p=root/name;shutil.copyfile(Path('/host-tls')/name,p);p.chmod(0o600);os.chown(p,65532,65532)
""",
        ],
        "volumes": ["front-tls:/front-tls", "./front-tls-input:/host-tls:ro"],
    }
    base["services"]["front"] = {
        "image": base["services"]["initialize"]["image"],
        "command": ["python", "/fixtures/personal_cli_tls.py"],
        "networks": ["default", "developer"],
        "volumes": [
            "front-tls:/front-tls:ro",
            "./tests/fixtures:/fixtures:ro",
            "./tls-input/ca.pem:/ca.pem:ro",
        ],
    }
    base["services"]["client"] = {
        "image": image,
        "networks": ["developer"],
        "command": ["python", "-c", "from threading import Event;Event().wait()"],
        "environment": {"SSL_CERT_FILE": "/ca.pem", "PYTHONDONTWRITEBYTECODE": "1"},
        "tmpfs": ["/client:uid=65532,gid=65532,mode=700,exec", "/tmp:mode=1777,exec"],
        "volumes": [
            "./client-files/keeplane.whl:/package/keeplane.whl:ro",
            "./client-files/opencode:/runtime/opencode:ro",
            "./tls-input/ca.pem:/ca.pem:ro",
            "./tests/fixtures/personal_cli_journey.py:/journey.py:ro",
            "./tests/fixtures/installed_cli_journey.py:/installed_cli_journey.py:ro",
        ],
    }
    for name in ("front", "client", "client-init"):
        service = base["services"][name]
        service.update(
            pull_policy="never", read_only=True, security_opt=["no-new-privileges:true"]
        )
        if name != "client-init":
            service.update(user="65532:65532", cap_drop=["ALL"])
    owned.base.write_text(json.dumps(base))
    config = json.loads(owned.compose("--profile", "*", "config", "--format", "json"))
    developer = config["networks"]["developer"]
    assert developer["internal"] and not developer.get("external")
    assert developer["name"].startswith(owned.project + "_")
    assert {
        name
        for name, service in config["services"].items()
        if "developer" in service.get("networks", {})
    } == {"front", "client"}
    client = config["services"]["client"]
    assert set(client["networks"]) == {"developer"} and "network_mode" not in client
    assert (
        not client.get("ports")
        and client["read_only"]
        and client["user"] == "65532:65532"
    )
    assert all(
        mount["type"] == "bind" and mount["read_only"] for mount in client["volumes"]
    )
    assert {mount["target"] for mount in client["volumes"]} == {
        "/package/keeplane.whl",
        "/runtime/opencode",
        "/ca.pem",
        "/journey.py",
        "/installed_cli_journey.py",
    }
    assert all(
        Path(mount["source"]).resolve().is_relative_to(root.resolve())
        for mount in client["volumes"]
    )
    owned.compose("run", "--rm", "--no-deps", "client-init")
    owned.compose(
        "up", "-d", "--no-build", "--pull", "never", "--no-deps", "front", "client"
    )
    owned.compose(
        "exec",
        "-T",
        "client",
        "python",
        "-c",
        """import time,urllib.request
deadline=time.monotonic()+15
while time.monotonic()<deadline:
 try:
  with urllib.request.urlopen('https://front:8443/health/ready',timeout=1) as response:
   assert response.status==200
  break
 except OSError:time.sleep(.1)
else:raise RuntimeError('TLS front was not ready')
""",
    )


def installed_personal(source, directory, app_image, client_image, wheel, binary):
    from tests.fixtures.personal_compose import PersonalCompose

    owned = PersonalCompose(
        source,
        directory,
        app_image,
        public_origin="https://front:8443",
        provider_module="tests.fixtures.personal_cli_provider",
    )
    report = {
        "passed": False,
        "cleaned": False,
        "stage": "bootstrap",
        "source_head": owned.source_head,
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "native_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "app_image": app_image,
        "client_image": client_image,
    }
    try:
        seed = owned.bootstrap()
        report["stage"] = "client-isolation"
        client_layer(owned, client_image, wheel, binary)
        seed["wheel_sha256"] = report["wheel_sha256"]
        report["stage"] = "installed-client"
        result = subprocess.run(
            owned.prefix + ["exec", "-T", "client", "python", "/journey.py"],
            cwd=owned.repo,
            env=owned.env,
            input=json.dumps(seed).encode(),
            capture_output=True,
            timeout=300,
            check=False,
        )
        for name, raw in (("stdout", result.stdout), ("stderr", result.stderr)):
            target = directory / ("client-" + name)
            target.write_bytes(raw)
            target.chmod(0o600)
        report["journey"] = json.loads(result.stdout)
        if result.returncode:
            diagnostic = subprocess.run(
                owned.prefix
                + ["exec", "-T", "client", "cat", "/client/command-failure.json"],
                cwd=owned.repo,
                env=owned.env,
                capture_output=True,
                timeout=10,
                check=False,
            )
            path = directory / "client-command-failure.json"
            path.write_bytes(diagnostic.stdout)
            path.chmod(0o600)
        assert result.returncode == 0 and report["journey"]["passed"]
        report["journey_passed"] = True
    except Exception as error:
        report["error_class"] = type(error).__name__
        try:
            report["provider_before_cleanup"] = owned.provider_status()
            report["diagnostics"] = owned.failure_diagnostics(directory / "diagnostics")
        except Exception as diagnostic_error:  # noqa: BLE001 - keep the original failed-stage exception.
            report["diagnostic_error_class"] = type(diagnostic_error).__name__
        raise
    finally:
        try:
            owned.cleanup()
            assert not owned.command(
                [
                    "docker",
                    "network",
                    "ls",
                    "-q",
                    "--filter",
                    "label=com.docker.compose.project=" + owned.project,
                ]
            )
            report["cleaned"] = True
        finally:
            report["passed"] = bool(report.get("journey_passed") and report["cleaned"])
            (directory / "installed-personal-cli-report.json").write_text(
                json.dumps(report)
            )
    assert report["passed"]
