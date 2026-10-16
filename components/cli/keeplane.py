"""Sign in, use projects and manage your own provider keys."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

if __package__:
    from . import (
        account_session,
        browser_login,
        coding,
        credential_refresh,
        device_login,
        opencode_adapter,
        provider_keys,
    )
    from .credential_profile import ProfileError, opened
    from .project_registration import register
    from .server_connection import ConnectionError, account, models
else:
    import account_session
    import browser_login
    import coding
    import credential_refresh
    import device_login
    import opencode_adapter
    import provider_keys
    from credential_profile import ProfileError, opened
    from project_registration import register
    from server_connection import ConnectionError, account, models


def project_command(action, profile_path, project_id, name=None):
    with opened(profile_path) as profile:
        credential = profile.load()
        actor = account(credential.issuer, credential.access_token)
        if actor["id"] != credential.actor_id:
            raise ProfileError("The server account changed; sign in again.")
        if action == "register-project":
            result = register(
                credential.issuer, project_id, name, credential.access_token
            )
        elif action == "models":
            result = models(credential.issuer, project_id, credential.access_token)
        else:
            raise ValueError("Choose a project command")
        output = json.dumps(result, indent=2)
        for secret in (credential.access_token, credential.refresh_token):
            output = output.replace(secret, "[redacted]")
        return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login", help="Sign in through the browser")
    login.add_argument("--server", required=True)
    login.add_argument("--profile", required=True)
    login.add_argument("--timeout", type=int, default=120)
    login.add_argument("--device", action="store_true", help="Sign in using a code on another browser")
    init = commands.add_parser("init", help="Preview existing project instructions and settings")
    init.add_argument("--preview", action="store_true", required=True)
    init.add_argument("--directory", type=Path, default=Path.cwd())
    code = commands.add_parser("code", help="Run a local coding turn through the protected gateway")
    for flag in ("profile", "project", "name", "model", "runtime", "gateway"):
        code.add_argument("--" + flag, required=True)
    code.add_argument("--directory", type=Path, default=Path.cwd())
    code.add_argument("--timeout", type=float, default=300)
    code.add_argument("--instructions", action="append", default=[], type=Path)
    code.add_argument("--state-dir", type=Path)
    code.add_argument("--session")
    code.add_argument("prompt")
    keys = commands.add_parser("keys", help="Manage your server-held model provider keys")
    key_commands = keys.add_subparsers(dest="key_action", required=True)
    for action in ("set", "status", "remove"):
        command = key_commands.add_parser(action)
        command.add_argument("--profile", required=True)
        command.add_argument("--model", required=True)
        if action == "set":
            command.add_argument("--key-stdin", action="store_true", help="Read the key from a pipe instead of the hidden prompt")
    for action, help_text in {
        "whoami": "Show the current account",
        "refresh": "Rotate this CLI credential pair once",
        "logout": "Revoke this CLI session and remove its local credential",
        "forget": "Remove only the local credential",
        "register-project": "Record account use of an explicit project",
        "models": "List the project's currently allowed models",
    }.items():
        command = commands.add_parser(action, help=help_text)
        command.add_argument("--profile", required=True)
        if action in {"register-project", "models"}:
            command.add_argument("--project", required=True)
        if action == "register-project":
            command.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            if sys.version_info < (3, 11):
                print("Migration preview requires Python 3.11 or newer.", file=sys.stderr)
                return 2
            if __package__:
                from .migration_preview import report
            else:
                from migration_preview import report
            return report(args.directory)
        elif args.command == "login":
            if args.device:
                device_login.login(args.server, args.profile, timeout=args.timeout)
            else:
                print("Opening Keeplane sign-in in your browser.")
                browser_login.login(args.server, args.profile, timeout=args.timeout)
            output = "Signed in to Keeplane."
        elif args.command in {"whoami", "logout", "forget"}:
            output = account_session.run(args.command, args.profile)
        elif args.command == "refresh":
            output = credential_refresh.refresh(args.profile)
        elif args.command == "keys":
            output = provider_keys.run(args.key_action, args.profile, args.model,
                                       key_stdin=getattr(args, "key_stdin", False))
        elif args.command == "code":
            with opencode_adapter.termination_requested() as cancelled:
                result = coding.run(
                    args.profile, args.project, args.name, args.model, args.runtime,
                    args.directory, args.gateway, args.prompt, args.timeout,
                    cancelled=cancelled, instructions=args.instructions,
                    state_dir=args.state_dir, session=args.session,
                )
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            return result.returncode
        else:
            output = project_command(
                args.command, args.profile, args.project, getattr(args, "name", None)
            )
        print(output)
    except (ProfileError, ConnectionError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("Coding turn timed out; review any edits before retrying.", file=sys.stderr)
        return 124
    except opencode_adapter.Cancelled:
        print("Coding turn terminated; review any edits before retrying.", file=sys.stderr)
        return 143
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except (ValueError, TypeError, OSError):
        print("Cannot complete this Keeplane command securely.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
