"""Build and start Keeplane locally. Accounts and models are kept between restarts."""

import argparse
import hashlib
import http.cookiejar
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

REPO = Path(__file__).resolve().parents[2]
LEGACY_RUNTIME = Path("/private/tmp/keeplane-accounts-trial")
RUNTIME = LEGACY_RUNTIME if LEGACY_RUNTIME.is_dir() else REPO / ".keeplane/local"
ADMIN_UI = REPO / "components/admin-ui"
MODEL = REPO / "models/qwen2.5-coder-0.5b-instruct-q4_k_m.gguf"
EXPECTED_MODEL_SHA256 = (
    "1d9614638d18024d0fbb36575a15f1302a3adf044df10345688ec4f6e1c4ff32"
)
MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B-Instruct-GGUF/resolve/"
    "0d4b0eeb9675b2da6dfaeb6fbf2ef1dff3e71e29/"
    "qwen2.5-coder-0.5b-instruct-q4_k_m.gguf"
)


def save_private(path, content):
    path.write_text(content)
    path.chmod(0o600)


def run(command, *, cwd=REPO, verbose=False, env=None):
    result = subprocess.run(
        command,
        check=False,
        cwd=cwd,
        text=True,
        stdout=None if verbose else subprocess.PIPE,
        stderr=None if verbose else subprocess.STDOUT,
        env=env,
    )
    if result.returncode:
        detail = "\n".join((result.stdout or "").splitlines()[-20:])
        raise RuntimeError(
            f"{' '.join(command[:3])} failed." + ("\n" + detail if detail else "")
        )
    return result.stdout or ""


# The preview's fixture provider serves HTTPS, so developers' own keys reach it
# the way they reach a real provider: Keeplane never sends a key over plain
# HTTP. Only the preview's app and gateway containers trust this test CA
# (SSL_CERT_FILE in compose.yaml); nothing else does.
TLS_CONFIG = """[req]
distinguished_name = name
prompt = no
[name]
CN = {name}
[ca]
basicConstraints = critical,CA:TRUE
keyUsage = critical,keyCertSign,cRLSign
subjectKeyIdentifier = hash
[provider]
subjectAltName = DNS:cloud-provider
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
"""


def preview_tls(directory, days=90):
    """A new test CA and certificate for `cloud-provider` on every start.

    The CA's private key is used once and deleted with its temporary folder;
    the app and gateway are recreated on every start, and the fixture reads
    its certificate for each connection, so they all see the new pair.
    """
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    with tempfile.TemporaryDirectory(prefix="keeplane-preview-tls-") as work:
        work = Path(work)
        for name, cn in (
            ("ca", "Keeplane preview test CA"),
            ("provider", "cloud-provider"),
        ):
            (work / f"{name}.cnf").write_text(TLS_CONFIG.format(name=cn))

        def openssl(*arguments):
            result = subprocess.run(
                ["openssl", *arguments],
                cwd=work,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(
                    "Could not make the preview's test certificate: "
                    + (result.stderr.strip().splitlines() or ["openssl failed"])[-1]
                )

        common = ["-newkey", "rsa:2048", "-nodes", "-sha256"]
        openssl(
            "req",
            "-x509",
            *common,
            "-keyout",
            "ca.key",
            "-out",
            "ca.pem",
            "-days",
            str(days),
            "-config",
            "ca.cnf",
            "-extensions",
            "ca",
        )
        openssl(
            "req",
            "-new",
            *common,
            "-keyout",
            "provider.key",
            "-out",
            "provider.csr",
            "-config",
            "provider.cnf",
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
            str(days),
            "-sha256",
            "-extfile",
            "provider.cnf",
            "-extensions",
            "provider",
        )
        # Written in place, so a running container's file mount sees them.
        for name, mode in (
            ("provider.key", 0o600),
            ("provider.pem", 0o644),
            ("ca.pem", 0o644),
        ):
            target = directory / name
            target.touch(mode=mode)
            target.chmod(mode)
            target.write_bytes((work / name).read_bytes())


def prerequisites(verbose=False):
    if sys.version_info < (3, 9):
        raise RuntimeError("Python 3.9 or newer is required.")
    for tool in ("node", "npm", "docker", "openssl"):
        if not shutil.which(tool):
            raise RuntimeError(
                f"{tool} is missing. See docs/guide/local-preview.md for prerequisites."
            )
    version = (
        subprocess.check_output(["node", "--version"], text=True).strip().lstrip("v")
    )
    if tuple(int(part) for part in version.split(".")[:2]) < (22, 12):
        raise RuntimeError(f"Node.js 22.12 or newer is required; found {version}.")
    run(["docker", "info", "--format", "{{.ServerVersion}}"], verbose=verbose)
    help_text = subprocess.check_output(
        ["docker", "compose", "up", "--help"], text=True
    )
    if "--wait" not in help_text:
        raise RuntimeError(
            "Docker Compose with 'up --wait' support is required. Update Docker Compose."
        )


def prepare(port=3000, context_size=4096, runtime_port=5000):
    if not MODEL.is_file():
        MODEL.parent.mkdir(parents=True, exist_ok=True)
        partial = MODEL.with_suffix(MODEL.suffix + ".part")
        print(
            "Downloading the pinned local Qwen model; this can take several minutes.",
            flush=True,
        )
        digest = hashlib.sha256()
        try:
            with (
                urlopen(MODEL_URL, timeout=120) as source,
                partial.open("wb") as target,
            ):
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    target.write(chunk)
            if digest.hexdigest() != EXPECTED_MODEL_SHA256:
                raise RuntimeError(
                    "Downloaded Qwen model checksum does not match the pinned version"
                )
            partial.replace(MODEL)
        finally:
            partial.unlink(missing_ok=True)
    digest = hashlib.sha256()
    with MODEL.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != EXPECTED_MODEL_SHA256:
        raise RuntimeError(f"Local Qwen model checksum does not match: {MODEL}")
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name in (
        "first-admin-password",
        "cloud-provider-key",
        "gateway-runtime-key",
        "gateway-admin-key",
    ):
        path = RUNTIME / name
        if not path.exists():
            save_private(path, secrets.token_urlsafe(32) + "\n")
    preview_tls(RUNTIME / "cloud-provider-tls")
    key_hashes = {
        name: hashlib.sha256((RUNTIME / name).read_text().strip().encode()).hexdigest()
        for name in ("gateway-runtime-key", "gateway-admin-key")
    }
    save_private(
        RUNTIME / ".env",
        f"KEEPLANE_RUNTIME_DIR={RUNTIME}\n"
        f"KEEPLANE_PORT={port}\nKEEPLANE_RUNTIME_PORT={runtime_port}\n"
        f"QWEN_CONTEXT_TOKENS={context_size}\n"
        f"GATEWAY_RUNTIME_KEY_HASH=sha256:{key_hashes['gateway-runtime-key']}\n"
        f"GATEWAY_ADMIN_KEY_HASH=sha256:{key_hashes['gateway-admin-key']}\n",
    )


def build_admin_ui(verbose=False):
    """Build the React screen from the committed lockfile before starting Docker."""
    run(
        ["npm", "ci", "--prefer-offline", "--no-audit", "--no-fund"],
        cwd=ADMIN_UI,
        verbose=verbose,
    )
    run(["npm", "run", "build"], cwd=ADMIN_UI, verbose=verbose)


def wait_preview(base="http://127.0.0.1:3000", timeout=120):
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    deadline = time.monotonic() + timeout
    signed_in = False
    last_error = "The application has not answered yet."

    def change(path, body):
        with opener.open(base + "/api/auth-options", timeout=3) as response:
            csrf = json.load(response)["csrf_token"]
        request = Request(
            base + path,
            method="POST",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": base,
                "X-CSRFToken": csrf,
                "X-Keeplane-Action": "1",
            },
        )
        return opener.open(request, timeout=3)

    try:
        while time.monotonic() < deadline:
            try:
                if not signed_in:
                    try:
                        with urlopen(base + "/api/identity", timeout=3):
                            raise RuntimeError(
                                "The admin API allowed anonymous access. Startup stopped."
                            )
                    except HTTPError as error:
                        if error.code != 401:
                            raise
                    with change(
                        "/api/session",
                        {
                            "username": "first-admin",
                            "password": (RUNTIME / "first-admin-password")
                            .read_text()
                            .strip(),
                        },
                    ):
                        signed_in = True
                with opener.open(base + "/health", timeout=3) as response:
                    if (
                        response.status == 200
                        and json.load(response).get("gateway") == "ready"
                    ):
                        return
                    last_error = "The model gateway is not ready."
            except HTTPError as error:
                if error.code in (400, 401, 403, 404, 429):
                    raise RuntimeError(
                        f"Startup check at {base} was refused (HTTP {error.code}). "
                        "Check the configured address and first-admin password file."
                    ) from error
                last_error = f"The application or gateway returned HTTP {error.code}."
            except (URLError, TimeoutError, ValueError, OSError, KeyError) as error:
                last_error = f"The application is not ready ({type(error).__name__})."
            time.sleep(2)
        raise RuntimeError(
            f"Keeplane was not ready after {timeout} seconds. {last_error} "
            "Inspect the app and gateway logs with 'docker compose logs app gateway'."
        )
    finally:
        if signed_in:
            # Startup verifies one real session, then revokes it, including on failure.
            try:
                with change("/sign-out", {}):
                    pass
            except (HTTPError, URLError, TimeoutError, ValueError, OSError, KeyError):
                print(
                    "Could not close the startup-check session; it will expire automatically.",
                    file=sys.stderr,
                )


def retire_old_preview():
    """Remove the former port 3001 preview's containers, running or stopped.

    They belong to the old keeplane-accounts-trial Compose project and mount the
    account volume this preview shares. Their data stays in the volume; the
    containers are never started again, and a stopped one would still hold the
    volume and make `docker volume rm` fail during a full reset.
    """
    result = subprocess.run(
        [
            "docker",
            "ps",
            "--all",
            "--filter",
            "label=com.docker.compose.project=keeplane-accounts-trial",
            "--format",
            "{{.Names}}",
        ],
        check=True,
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    names = result.stdout.splitlines()
    if names:
        print(
            "Removing the earlier preview's containers (its data stays in the volume)…",
            flush=True,
        )
        run(["docker", "rm", "--force", *names])


def earlier_database_notices(env, since):
    """Repeat this start's volume-step notices (an earlier preview database left unused)."""
    logs = run(
        [
            "docker",
            "compose",
            "--env-file",
            str(RUNTIME / ".env"),
            "logs",
            "--no-color",
            "--no-log-prefix",
            "--since",
            since,
            "account-volume-init",
        ],
        env=env,
    )
    return list(
        dict.fromkeys(
            line.strip()
            for line in logs.splitlines()
            if line.strip().startswith("Notice: ")
        )
    )


def main(argv=None):
    global RUNTIME
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        type=int,
        default=os.environ.get("KEEPLANE_PORT", "3000"),
        help="Local browser port (default: 3000, or KEEPLANE_PORT)",
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=os.environ.get("KEEPLANE_RUNTIME_DIR", RUNTIME),
        help="Private local credential directory; existing credentials are reused",
    )
    parser.add_argument(
        "--context-size",
        type=int,
        default=os.environ.get("QWEN_CONTEXT_TOKENS", "4096"),
        help="Bundled demo runner context, in tokens (default: 4096)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show dependency and container build output",
    )
    parser.add_argument(
        "--runtime-port",
        type=int,
        default=5000,
        help="Loopback port of the guarded model gateway for the CLI (default: 5000)",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.context_size < 512:
        parser.error("--context-size must be at least 512 tokens")
    if not 1 <= args.runtime_port <= 65535 or args.runtime_port == args.port:
        parser.error(
            "--runtime-port must be between 1 and 65535 and different from --port"
        )
    RUNTIME = Path(args.runtime_dir).expanduser().resolve()
    print("Checking Python, Node.js and Docker…", flush=True)
    prerequisites(args.verbose)
    print("Preparing the demo model and local credentials…", flush=True)
    prepare(args.port, args.context_size, args.runtime_port)
    print("Installing dependencies and building the web UI…", flush=True)
    build_admin_ui(args.verbose)
    retire_old_preview()
    run(["docker", "volume", "create", "keeplane-accounts-trial_model-approvals"])
    print("Starting containers…", flush=True)
    compose_env = {
        **os.environ,
        **dict(
            line.split("=", 1) for line in (RUNTIME / ".env").read_text().splitlines()
        ),
    }
    # A few seconds' margin for the Docker host's clock; earlier starts' logs are older.
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 5))
    run(
        [
            "docker",
            "compose",
            "--env-file",
            str(RUNTIME / ".env"),
            "--profile",
            "qwen",
            "up",
            "-d",
            "--build",
            "--wait",
        ],
        verbose=args.verbose,
        env=compose_env,
    )
    for notice in earlier_database_notices(compose_env, since):
        print(notice, flush=True)
    base = f"http://127.0.0.1:{args.port}"
    print("Checking sign-in and the model gateway…", flush=True)
    wait_preview(base)
    # ADR 028: CLI sign-in, the guarded gateway and the model enroller, which
    # enrols every model saved in Models; a fresh gateway on every start.
    from guarded_runtime import enroller_report, install

    print("Starting CLI sign-in and the guarded model gateway…", flush=True)
    gateway = install(
        REPO,
        RUNTIME,
        [],
        args.runtime_port,
        env=compose_env,
        wait_ready=lambda: wait_preview(base),
    )
    report = enroller_report(REPO, RUNTIME, env=compose_env)
    print(
        report
        or "The model enroller has not reported yet. "
        "Check it with 'docker compose -f compose.yaml -f deploy/local/runtime.yaml logs model-enroller'."
    )
    print(f"Keeplane is ready: {base}")
    print(f"Guarded model gateway for the CLI: {gateway}")
    print(f"Sign in from the CLI: keeplane login --server {base} --profile PROFILE")
    print("First admin username: first-admin")
    print(f"First admin password file: {RUNTIME / 'first-admin-password'}")
    print(f"Configuration file: {RUNTIME / '.env'}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Keeplane could not start: {error}", file=sys.stderr)
        sys.exit(1)
