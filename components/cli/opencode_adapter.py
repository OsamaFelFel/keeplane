"""Run one experimental local coding turn through a protected gateway."""

import argparse
from contextlib import contextmanager
import getpass
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

if __package__:
    from .instructions import snapshot
else:
    from instructions import snapshot


VERSION = "2.0.27"


class Cancelled(KeyboardInterrupt):
    """SIGTERM requested termination of the active coding turn."""


class Termination:
    requested = False
    active = False

    def request(self, *_):
        self.requested = True
        if self.active:
            raise Cancelled


@contextmanager
def termination_requested():
    cancelled = Termination()
    previous = signal.signal(signal.SIGTERM, cancelled.request)
    try:
        yield cancelled
    finally:
        signal.signal(signal.SIGTERM, previous)


def coding_turn(command, *, input, env, cwd, timeout, cancelled=None):
    if cancelled is not None and cancelled.requested:
        raise Cancelled
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, env=env, cwd=cwd,
                               start_new_session=True)
    try:
        try:
            if cancelled is not None:
                # Defer a signal during Popen until we own its process.
                cancelled.active = True
                if cancelled.requested:
                    raise Cancelled
            output, errors = process.communicate(input, timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            if cancelled is not None:
                cancelled.active = False
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            # Detached children may keep inherited pipes open. Wait only for
            # the owned parent; closing our pipes below never waits for EOF.
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            raise
        return subprocess.CompletedProcess(command, process.returncode, output, errors)
    finally:
        if cancelled is not None:
            cancelled.active = False
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def run(binary, directory, gateway, model, prompt, grant, timeout=300, *, cancelled=None, instructions=()):
    """Use a disposable profile; the gateway remains responsible for authorization."""
    if os.name != "posix":
        raise ValueError("This prototype currently supports macOS and Linux.")
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
    if not isinstance(grant, str) or re.fullmatch(r"[A-Za-z0-9._~-]{1,4096}", grant) is None:
        raise ValueError("Gateway credentials must use only letters, digits, dot, underscore, tilde or hyphen.")
    if timeout <= 0 or not prompt.strip():
        raise ValueError("Provide a prompt and a positive timeout.")
    binary = str(Path(binary).expanduser().resolve(strict=True))
    directory = str(Path(directory).expanduser().resolve(strict=True))
    if not Path(directory).is_dir():
        raise ValueError("The working directory must be a directory.")
    instruction_snapshot = snapshot(directory, instructions) if instructions else None
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
        if instruction_snapshot:
            config["plugins"] = [{
                "package": str(Path(__file__).with_name("instruction_plugin").resolve()),
                "options": instruction_snapshot,
            }]
        configuration = json.dumps(config, ensure_ascii=False)
        if len(configuration.encode("utf-8")) > 120 * 1024:
            raise ValueError("Serialized runtime configuration exceeds 120 KiB; choose smaller instruction files.")
        # The credential is absent from configuration, process arguments and disk files.
        environment.update({
            "KEEPLANE_RUNTIME_GRANT": grant,
            "OPENCODE_CONFIG_CONTENT": configuration,
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
        result = coding_turn(
            [binary, "run", "--standalone", "--format", "json",
             "--model", "keeplane/" + model],
            input=prompt, env=environment, cwd=directory,
            timeout=timeout,
            cancelled=cancelled,
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
    parser.add_argument("--instructions", action="append", default=[], type=Path,
                        help="Reviewed UTF-8 instruction file directly in --directory; repeatable")
    parser.add_argument("prompt")
    args = parser.parse_args()
    grant = os.environ.pop("KEEPLANE_GATEWAY_GRANT", None)
    try:
        if grant is None:
            if not sys.stdin.isatty():
                parser.error("Set KEEPLANE_GATEWAY_GRANT for a noninteractive invocation.")
            grant = getpass.getpass("Keeplane gateway credential: ")
        with termination_requested() as cancelled:
            result = run(args.runtime, args.directory, args.gateway, args.model,
                         args.prompt, grant, args.timeout, cancelled=cancelled,
                         instructions=args.instructions)
    except subprocess.TimeoutExpired:
        print("Coding turn timed out; review any edits before retrying.", file=sys.stderr)
        return 124
    except Cancelled:
        print("Coding turn terminated; review any edits before retrying.", file=sys.stderr)
        return 143
    except KeyboardInterrupt:
        print("Coding turn cancelled; review any edits before retrying.", file=sys.stderr)
        return 130
    except (OSError, ValueError) as error:
        print(str(error).replace(grant or "\0", "[redacted]"), file=sys.stderr)
        return 2
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
