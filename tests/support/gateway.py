"""Private test helpers for gateway management and provider-key inspection."""

import json
import os
import re
import subprocess
import uuid
from pathlib import Path

from tests.support.reporting import report_path

REPO = Path(__file__).resolve().parents[2]
RESOURCE_PATH = "/api/config/resources/llm.model"

GATEWAY_SCRIPT = """
import json, os, pathlib, sys, urllib.error, urllib.request
method, path, payload = sys.argv[1:]
data = None if payload == '-' else payload.encode()
request = urllib.request.Request(os.environ['GATEWAY_URL'] + path, data=data, method=method)
key_type = 'admin' if path.startswith('/api/') else 'runtime'
key = pathlib.Path(os.environ['GATEWAY_' + key_type.upper() + '_KEY_FILE']).read_text().strip()
request.add_header('Authorization', 'Bearer ' + key)
if data is not None:
    request.add_header('Content-Type', 'application/json')
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        status, raw = response.status, response.read()
except urllib.error.HTTPError as error:
    status, raw = error.code, error.read()
try:
    body = json.loads(raw)
except ValueError:
    body = {'raw': raw.decode(errors='replace')[:300]}
print(json.dumps({'status': status, 'body': body}))
"""


def command_failure(code, stderr="", *, timed_out=False):
    # Keep useful Python transport causes without copying messages or credentials.
    allowed = (
        "TimeoutError", "ConnectionRefusedError", "ConnectionResetError",
        "BrokenPipeError", "RemoteDisconnected", "URLError", "HTTPError",
        "FileNotFoundError", "PermissionError", "JSONDecodeError", "SSLError",
        "SSLCertVerificationError", "KeyError", "ValueError", "OSError",
    )
    pattern = r"(?m)^(?:[A-Za-z_][A-Za-z0-9_]*\.)*(" + "|".join(allowed) + r")(?::|$)"
    names = list(dict.fromkeys(re.findall(pattern, stderr)))
    details = {
        "failed": True,
        "kind": "command_timeout" if timed_out else "remote_exit",
        "exit_code": code,
        "remote_exception_types": names,
    }
    summary = "timeout after 30 seconds" if timed_out else f"exit {code}"
    if names:
        summary += "; " + ", ".join(names)
    try:
        path = report_path("gateway-command-" + uuid.uuid4().hex + ".json")
        path.write_text(json.dumps(details, indent=2) + "\n")
        summary += "; diagnostic: " + str(path)
    except OSError:
        summary += "; diagnostic report could not be written"
    return RuntimeError("Private gateway test command failed (" + summary + ")")


def app_exec(*args):
    base = os.environ.get("KEEPLANE_BASE_URL", "http://127.0.0.1:3000")
    if base.rstrip("/") == "http://127.0.0.1:3000":
        command = [
            "docker",
            "compose",
            "--env-file",
            "/private/tmp/keeplane-accounts-trial/.env",
            "exec",
            "-T",
            "app",
        ]
    elif base.rstrip("/") == "http://127.0.0.1:13000":
        kubeconfig = os.environ.get(
            "KEEPLANE_KUBECONFIG", "/private/tmp/keeplane-kind-kubeconfig"
        )
        prefix = ["kubectl", "--kubeconfig", kubeconfig]
        context = subprocess.check_output(
            prefix + ["config", "current-context"], text=True
        ).strip()
        if context != "kind-keeplane":
            raise RuntimeError("Refusing gateway test outside kind-keeplane")
        command = prefix + ["-n", "keeplane", "exec", "deployment/keeplane-app", "--"]
    else:
        raise RuntimeError("Refusing gateway test against an unknown preview")
    try:
        process = subprocess.run(
            command + list(args),
            check=False,
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        args = ()
        raise command_failure(None, timed_out=True) from None
    if process.returncode:
        failure = command_failure(process.returncode, process.stderr)
        # Pytest also renders function arguments; keep private payloads out of them.
        args = ()
        process = None
        raise failure from None
    return process.stdout


def gateway_call(method, path, body=None):
    payload = "-" if body is None else json.dumps(body)
    body = None
    try:
        output = app_exec(
            "python",
            "-c",
            GATEWAY_SCRIPT,
            method,
            path,
            payload,
        )
    finally:
        payload = None
    result = json.loads(output)
    return result["status"], result["body"]


def key_files():
    script = "import json, pathlib; print(json.dumps(sorted(p.name for p in pathlib.Path('/provider-keys').glob('key-*'))))"
    return set(json.loads(app_exec("python", "-c", script)))


def key_metadata(path):
    script = "import json, os, sys; s=os.stat(sys.argv[1]); print(json.dumps({'uid':s.st_uid,'mode':oct(s.st_mode & 0o777)}))"
    return json.loads(app_exec("python", "-c", script, path))


def resource(name):
    status, result = gateway_call("GET", RESOURCE_PATH)
    if status != 200:
        return status, None
    return status, next(
        (
            item["value"]
            for item in result.get("resources", [])
            if item.get("id") == name
        ),
        None,
    )
