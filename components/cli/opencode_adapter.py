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
# Built-in runtime plugins turned off by a "-" directive: the web fetch tool,
# the web search tool and every hosted web search provider.
DISABLED_BUILTINS = (
    "-opencode.tool.webfetch",
    "-opencode.tool.websearch",
    "-opencode.websearch.*",
)
# D185: cloud models only through API keys, and only through the gateway.
# Every built-in provider plugin is turned off: they add the runtime's own
# sign-ins (ChatGPT and OpenAI subscriptions, GitHub Copilot, GitLab and
# others, with their OAuth listeners), local-runner discovery and package
# installs. The gateway provider comes from these settings, not a plugin.
DISABLED_PROVIDERS = ("-opencode.provider.*",)
PROVIDER = "keeplane"
PROVIDER_PACKAGE = "@opencode/ai/providers/openai-compatible"
# Only this settings' provider may be used; the catalogue's other providers
# (OpenAI, Anthropic and the rest) are removed before a turn starts.
PROVIDER_POLICIES = (
    {"action": "provider.use", "resource": "*", "effect": "deny"},
    {"action": "provider.use", "resource": PROVIDER, "effect": "allow"},
)
# ADR 029: ask for token usage on streamed answers (stream_options.include_usage).
MODEL_COMPATIBILITY = {"supportsUsageInStreaming": True}
SETTINGS_KEYS = frozenset({"providers", "model", "share", "snapshots", "websearch",
                           "plugins", "experimental"})
# Words that name a sign-in, a stored credential or a key anywhere in the
# settings. The gateway credential reaches the runtime only through
# KEEPLANE_RUNTIME_GRANT, named in "env".
SIGN_IN_WORDS = ("auth", "login", "apikey", "accesstoken", "refreshtoken", "bearer",
                 "credential", "subscription", "accountid", "secret", "password")


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


def _keys(value, depth=0):
    if depth > 32:
        raise ValueError("Runtime settings are nested too deeply.")
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item, depth + 1)


def check_settings(config, gateway, instruction_plugin=None):
    """Refuse runtime settings other than the reviewed gateway-only shape (D185).

    Exactly these keys, each with its reviewed value: one provider, `keeplane`,
    through the built-in OpenAI-compatible package, with only the gateway
    address, the grant from KEEPLANE_RUNTIME_GRANT and at most the project
    header; one model entry that is exactly its name and the streamed-usage
    flag; sharing and snapshots off; web search off; the web-tool and provider
    plugin directives; at most Keeplane's own instruction plugin; and the
    gateway-only provider policy. No key anywhere may name a sign-in, key or
    credential.
    """
    if not isinstance(config, dict) or set(config) != SETTINGS_KEYS:
        raise ValueError("Runtime settings have a missing or unreviewed key.")
    providers = config["providers"]
    if not isinstance(providers, dict) or list(providers) != [PROVIDER]:
        raise ValueError("Runtime settings must name only the Keeplane gateway as a provider.")
    provider = providers[PROVIDER]
    if (not isinstance(provider, dict)
            or set(provider) - {"package", "env", "settings", "models", "headers"}
            or provider.get("package") != PROVIDER_PACKAGE
            or provider.get("env") != ["KEEPLANE_RUNTIME_GRANT"]
            or provider.get("settings") != {"baseURL": gateway}):
        raise ValueError("The gateway provider may only use the gateway address and grant.")
    headers = provider.get("headers", {})
    if (not isinstance(headers, dict) or set(headers) - {"X-Keeplane-Project-ID"}
            or not all(isinstance(value, str) for value in headers.values())):
        raise ValueError("The gateway provider may only send the project header.")
    models = provider.get("models")
    if not isinstance(models, dict) or len(models) != 1:
        raise ValueError("Runtime settings must use one gateway model.")
    [(model, options)] = models.items()
    if config["model"] != PROVIDER + "/" + model:
        raise ValueError("Runtime settings must use one gateway model.")
    if options != {"name": model, "compatibility": MODEL_COMPATIBILITY}:
        raise ValueError("The gateway model may only hold its name and the streamed-usage flag.")
    if config["share"] != "disabled" or config["snapshots"] is not False:
        raise ValueError("Runtime settings must keep sharing and snapshots off.")
    if config["websearch"] is not False:
        raise ValueError("Runtime settings must keep web search off.")
    for key in _keys(config):
        folded = str(key).lower().replace("-", "").replace("_", "")
        if any(word in folded for word in SIGN_IN_WORDS):
            raise ValueError("Runtime settings may not hold a sign-in, credential or key.")
    if config["experimental"] != {"policies": list(PROVIDER_POLICIES)}:
        raise ValueError("Runtime settings must keep the gateway-only provider policy.")
    plugins = config["plugins"]
    expected = list(DISABLED_BUILTINS) + list(DISABLED_PROVIDERS)
    if not isinstance(plugins, list) or [row for row in plugins if isinstance(row, str)] != expected:
        raise ValueError("Runtime settings must keep web tools and provider sign-ins off.")
    packages = [row for row in plugins if not isinstance(row, str)]
    allowed = [] if instruction_plugin is None else [instruction_plugin]
    if (not all(isinstance(row, dict) and set(row) == {"package", "options"} for row in packages)
            or [row["package"] for row in packages] != allowed):
        raise ValueError("Runtime settings may only add Keeplane's instruction plugin.")


def turn_usage(stdout):
    """Token usage the runtime reported for one turn, or None (ADR 029).

    Each model request of the turn ends with a step_finish event whose tokens
    come from the gateway's answer. Cached input counts as input and reasoning
    as output. A request whose answer carried no usage reports zero tokens and
    is counted in requests_without_usage. Requests of child sessions
    (subagents) are not in the runtime's output, so they are not counted.
    """
    totals = {"input_tokens": 0, "output_tokens": 0, "requests": 0,
              "requests_without_usage": 0}

    def count(value):
        return value if type(value) is int and value > 0 else 0

    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "step_finish":
            continue
        part = event.get("part")
        tokens = part.get("tokens") if isinstance(part, dict) else None
        tokens = tokens if isinstance(tokens, dict) else {}
        cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
        used_in = count(tokens.get("input")) + count(cache.get("read")) + count(cache.get("write"))
        used_out = count(tokens.get("output")) + count(tokens.get("reasoning"))
        totals["requests"] += 1
        if used_in + used_out == 0:
            totals["requests_without_usage"] += 1
        totals["input_tokens"] += used_in
        totals["output_tokens"] += used_out
    return totals if totals["requests"] else None


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
            "providers": {PROVIDER: {
                "package": PROVIDER_PACKAGE,
                "env": ["KEEPLANE_RUNTIME_GRANT"],
                "settings": {"baseURL": gateway.rstrip("/")},
                "models": {model: {"name": model, "compatibility": dict(MODEL_COMPATIBILITY)}},
            }},
            "model": PROVIDER + "/" + model,
            "share": "disabled", "snapshots": False,
            # ADR 009: no built-in web search or web fetch, so a turn never sends
            # its content to a service no admin set up.
            "websearch": False,
            "plugins": list(DISABLED_BUILTINS) + list(DISABLED_PROVIDERS),
            "experimental": {"policies": [dict(row) for row in PROVIDER_POLICIES]},
        }
        if account_context is not None:
            config["providers"][PROVIDER]["headers"] = {
                "X-Keeplane-Project-ID": account_context["project_id"],
            }
        instruction_plugin = None
        if instruction_snapshot:
            instruction_plugin = str(Path(__file__).with_name("instruction_plugin").resolve())
            config["plugins"].insert(0, {
                "package": instruction_plugin,
                "options": instruction_snapshot,
            })
        check_settings(config, gateway.rstrip("/"), instruction_plugin)
        configuration = json.dumps(config, ensure_ascii=False)
        if len(configuration.encode("utf-8")) > 120 * 1024:
            raise ValueError("Serialized runtime configuration exceeds 120 KiB; choose smaller instruction files.")
        # The credential is absent from configuration, process arguments and disk files.
        # ADR 009: the runtime downloads no model catalogue and runs no update
        # check of its own (the update policy file below says the same).
        environment.update({
            "KEEPLANE_RUNTIME_GRANT": grant,
            "OPENCODE_CONFIG_CONTENT": configuration,
            "OPENCODE_CONFIG_PROJECT_DISABLE": "1",
            "OPENCODE_DISABLE_MODELS_FETCH": "1",
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
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
        command = [binary, "run", "--standalone", "--format", "json", "--model", PROVIDER + "/" + model]
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
