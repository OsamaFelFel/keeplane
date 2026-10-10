"""Start the single protected Docker preview without replacing local data."""

import hashlib
import http.cookiejar
import json
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


REPO = Path(__file__).resolve().parents[2]
RUNTIME = Path("/private/tmp/keeplane-accounts-trial")
ADMIN_UI = REPO / "components/admin-ui/web"
MODEL = REPO / "models/qwen2.5-coder-0.5b-instruct-q4_k_m.gguf"
EXPECTED_MODEL_SHA256 = "1d9614638d18024d0fbb36575a15f1302a3adf044df10345688ec4f6e1c4ff32"
MODEL_URL = ("https://huggingface.co/Qwen/Qwen2.5-Coder-0.5B-Instruct-GGUF/resolve/"
             "0d4b0eeb9675b2da6dfaeb6fbf2ef1dff3e71e29/"
             "qwen2.5-coder-0.5b-instruct-q4_k_m.gguf")


def save_private(path, content):
    path.write_text(content)
    path.chmod(0o600)


def prepare():
    if not MODEL.is_file():
        MODEL.parent.mkdir(parents=True, exist_ok=True)
        partial = MODEL.with_suffix(MODEL.suffix + ".part")
        print("Downloading the pinned local Qwen model; this can take several minutes.", flush=True)
        digest = hashlib.sha256()
        try:
            with urlopen(MODEL_URL, timeout=120) as source, partial.open("wb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                    target.write(chunk)
            if digest.hexdigest() != EXPECTED_MODEL_SHA256:
                raise RuntimeError("Downloaded Qwen model checksum does not match the pinned version")
            partial.replace(MODEL)
        finally:
            partial.unlink(missing_ok=True)
    digest = hashlib.sha256()
    with MODEL.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != EXPECTED_MODEL_SHA256:
        raise RuntimeError(f"Local Qwen model checksum does not match: {MODEL}")
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    for name in ("first-admin-password", "cloud-provider-key"):
        path = RUNTIME / name
        if not path.exists():
            save_private(path, secrets.token_urlsafe(32) + "\n")
    save_private(RUNTIME / ".env", f"KEEPLANE_RUNTIME_DIR={RUNTIME}\n")


def build_admin_ui():
    """Build the React screen from the committed lockfile before starting Docker."""
    if not (ADMIN_UI / "node_modules").is_dir():
        subprocess.run(["npm", "ci"], cwd=ADMIN_UI, check=True)
    subprocess.run(["npm", "run", "build"], cwd=ADMIN_UI, check=True)


def wait_preview():
    for _ in range(60):
        try:
            with urlopen("http://127.0.0.1:3000/api/identity", timeout=3) as response:
                raise RuntimeError(f"Admin API unexpectedly allowed anonymous access: HTTP {response.status}")
        except HTTPError as error:
            if error.code == 401:
                opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
                request = Request("http://127.0.0.1:3000/api/session", method="POST",
                                  data=json.dumps({"username": "first-admin", "password":
                                                   (RUNTIME / "first-admin-password").read_text().strip()}).encode(),
                                  headers={"Content-Type": "application/json"})
                try:
                    with opener.open(request, timeout=3) as response:
                        if response.status != 200:
                            continue
                    with opener.open("http://127.0.0.1:3000/health", timeout=3) as response:
                        if response.status == 200 and json.load(response).get("gateway") == "ready":
                            return
                except (HTTPError, URLError, TimeoutError, ValueError, OSError):
                    pass
        except (URLError, TimeoutError, OSError):
            pass
        time.sleep(2)
    raise RuntimeError("Protected Keeplane preview did not become ready within two minutes")


def retire_old_preview():
    """Stop the former port 3001 app before sharing its SQLite volume."""
    result = subprocess.run(["docker", "ps", "--filter",
                             "label=com.docker.compose.project=keeplane-accounts-trial",
                             "--format", "{{.Names}}"], check=True, cwd=REPO,
                            capture_output=True, text=True)
    names = result.stdout.splitlines()
    if names:
        subprocess.run(["docker", "stop", *names], check=True, cwd=REPO)


def main():
    prepare()
    build_admin_ui()
    retire_old_preview()
    subprocess.run(["docker", "volume", "create", "keeplane-accounts-trial_model-approvals"],
                   check=True, cwd=REPO, capture_output=True, text=True)
    subprocess.run(["docker", "compose", "--env-file", str(RUNTIME / ".env"),
                    "--profile", "qwen", "up", "-d", "--build", "--wait"], check=True, cwd=REPO)
    wait_preview()
    print("Keeplane: http://127.0.0.1:3000")
    print("First admin username: first-admin")
    print(f"First admin password file: {RUNTIME / 'first-admin-password'}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(f"Keeplane setup failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
