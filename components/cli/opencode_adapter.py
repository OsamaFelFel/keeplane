"""Run one experimental local coding turn through a protected gateway."""

import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit


VERSION = "2.0.27"


def run(binary, directory, gateway, model, prompt, grant, timeout=300):
    """Use a disposable profile; the gateway remains responsible for authorization."""
    url = urlsplit(gateway)
    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Gateway must be an HTTP(S) URL without credentials or query parameters.")
    if url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Use HTTPS for a gateway outside this machine.")
    if not model or any(character.isspace() for character in model) or "#" in model:
        raise ValueError("Provide a gateway model ID without whitespace or a variant suffix.")
    if not grant or any(character.isspace() for character in grant):
        raise ValueError("Provide a valid Keeplane gateway credential.")
    if timeout <= 0 or not prompt.strip():
        raise ValueError("Provide a prompt and a positive timeout.")
    binary = str(Path(binary).expanduser().resolve(strict=True))
    directory = str(Path(directory).expanduser().resolve(strict=True))
    if not Path(directory).is_dir():
        raise ValueError("The working directory must be a directory.")
    with tempfile.TemporaryDirectory(prefix="keeplane-cli-") as temporary:
        profile = Path(temporary)
        environment = {
            name: value
            for name, value in os.environ.items()
            if name in ("PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR")
        }
        for name, child in (
            ("HOME", "home"), ("XDG_CONFIG_HOME", "config"),
            ("XDG_CACHE_HOME", "cache"), ("XDG_DATA_HOME", "data"),
            ("XDG_STATE_HOME", "state"), ("TMPDIR", "tmp"),
        ):
            location = profile / child
            location.mkdir(mode=0o700)
            environment[name] = str(location)
        config = {
            "providers": {"keeplane": {
                "package": "@opencode/ai/providers/openai-compatible",
                "env": ["KEEPLANE_RUNTIME_GRANT"],
                "settings": {"baseURL": gateway.rstrip("/")},
                "models": {model: {"name": model}},
            }},
            "model": "keeplane/" + model,
            "share": "disabled", "snapshots": False,
        }
        # The credential is absent from configuration, process arguments and disk files.
        environment.update({
            "KEEPLANE_RUNTIME_GRANT": grant,
            "OPENCODE_CONFIG_CONTENT": json.dumps(config),
            "OPENCODE_CONFIG_PROJECT_DISABLE": "1",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_FFF": "1",
        })
        (profile / "config" / "opencode").mkdir()
        (profile / "config" / "opencode" / "opencode.json").write_text(
            '{"update":"disable"}\n'
        )
        version = subprocess.run(
            [binary, "--version"], env=environment, cwd=directory,
            capture_output=True, text=True, timeout=10, check=False,
        )
        if version.returncode or version.stdout.strip().removeprefix("opencode ").removeprefix("v") != VERSION:
            raise ValueError("This prototype requires OpenCode V2 " + VERSION + ".")
        result = subprocess.run(
            [binary, "run", "--standalone", "--format", "json",
             "--model", "keeplane/" + model],
            input=prompt, env=environment, cwd=directory,
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        result.stdout = result.stdout.replace(grant, "[redacted]")
        result.stderr = result.stderr.replace(grant, "[redacted]")
        # Some native failures are JSON error events despite an exit status of zero.
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "error":
                result.returncode = result.returncode or 1
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True, help="Path to OpenCode V2 2.0.27")
    parser.add_argument("--gateway", required=True, help="Protected gateway API base, including /v1")
    parser.add_argument("--model", required=True, help="Model ID registered in that gateway")
    parser.add_argument("--directory", type=Path, default=Path.cwd())
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("prompt")
    args = parser.parse_args()
    grant = os.environ.pop("KEEPLANE_GATEWAY_GRANT", None)
    try:
        if grant is None:
            if not sys.stdin.isatty():
                parser.error("Set KEEPLANE_GATEWAY_GRANT for a noninteractive invocation.")
            grant = getpass.getpass("Keeplane gateway credential: ")
        result = run(args.runtime, args.directory, args.gateway, args.model,
                     args.prompt, grant, args.timeout)
    except subprocess.TimeoutExpired:
        print("Coding turn timed out; review any edits before retrying.", file=sys.stderr)
        return 124
    except (OSError, ValueError) as error:
        print(str(error).replace(grant or "\0", "[redacted]"), file=sys.stderr)
        return 2
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
