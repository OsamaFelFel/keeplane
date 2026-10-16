"""Sign in, use projects and manage your own provider keys."""

import argparse
import json
import sys

if __package__:
    from . import account_session, browser_login, provider_keys
    from .credential_profile import ProfileError, opened
    from .project_registration import register
    from .server_connection import ConnectionError, account, models
else:
    import account_session
    import browser_login
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
        if args.command == "login":
            print("Opening Keeplane sign-in in your browser.")
            browser_login.login(args.server, args.profile, timeout=args.timeout)
            output = "Signed in to Keeplane."
        elif args.command in {"whoami", "logout", "forget"}:
            output = account_session.run(args.command, args.profile)
        elif args.command == "keys":
            output = provider_keys.run(args.key_action, args.profile, args.model,
                                       key_stdin=getattr(args, "key_stdin", False))
        else:
            output = project_command(
                args.command, args.profile, args.project, getattr(args, "name", None)
            )
        print(output)
    except (ProfileError, ConnectionError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
    except (ValueError, TypeError, OSError):
        print("Cannot complete this Keeplane command securely.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
