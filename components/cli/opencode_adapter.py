"""Run one experimental local coding turn through a protected gateway."""

import argparse
import getpass
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

if __package__:
    from .instructions import snapshot
    from .session_state import account_binding, managed
else:
    from instructions import snapshot
    from session_state import account_binding, managed


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


def coding_turn(command, *, input, env, cwd, timeout, cancelled=None, pass_fds=()):
    if cancelled is not None and cancelled.requested:
        raise Cancelled
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, env=env, cwd=cwd,
                               start_new_session=True, pass_fds=pass_fds)
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
                # The pinned runtime interrupts its session and cleans up
                # managed shell tools on SIGINT, including separate groups.
                process.send_signal(signal.SIGINT)
                process.wait(timeout=4)
            except (ProcessLookupError, subprocess.TimeoutExpired, KeyboardInterrupt):
                pass
            finally:
                # Also stop remaining members of our group if the runtime
                # exited early, ignored interruption or cleanup was interrupted.
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


def run(binary, directory, gateway, model, prompt, grant, timeout=300, *, cancelled=None, instructions=(), state_dir=None, session=None, account_context=None):
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
    if session is not None and (not isinstance(session, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session) is None):
        raise ValueError("Provide a native session ID.")
    host = "[" + url.hostname.lower() + "]" if ":" in url.hostname else url.hostname.lower()
    if url.port and url.port != {"https": 443, "http": 80}[url.scheme]:
        host += ":" + str(url.port)
    gateway = url._replace(netloc=host, path=url.path.rstrip("/")).geturl()
    binding = {"directory": directory, "gateway": gateway, "model": model, "version": VERSION}
    if account_context is not None:
        binding.update(account_binding(account_context))
    with managed(state_dir, binding, session) as state, tempfile.TemporaryDirectory(prefix="keeplane-cli-") as temporary:
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
        if account_context is not None:
            config["providers"]["keeplane"]["headers"] = {
                "X-Keeplane-Project-ID": account_context["project_id"],
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
        if state:
            environment["OPENCODE_DB"] = state.database
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
        command = [binary, "run", "--standalone", "--format", "json", "--model", "keeplane/" + model]
        if session:
            command += ["--session", session]
        result = coding_turn(
            command,
            input=prompt, env=environment, cwd=directory,
            timeout=timeout,
            cancelled=cancelled,
            pass_fds=(state.lock,) if state else (),
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
    parser.add_argument("--state-dir", type=Path, help="Private Keeplane-owned session directory outside the repository")
    parser.add_argument("--session", help="Resume this native session ID from --state-dir")
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
                         instructions=args.instructions, state_dir=args.state_dir,
                         session=args.session)
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
