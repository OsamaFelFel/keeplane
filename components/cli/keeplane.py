"""Sign in, code in any repo through Keeplane and manage your own provider keys."""

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
        project_identity,
        provider_keys,
        settings_file,
        sign_in_again,
        usage,
    )
    from .credential_profile import ProfileError, default_path, opened
    from .project_registration import register
    from .server_connection import ConnectionError, SignInExpired, account, models
else:
    import account_session
    import browser_login
    import coding
    import credential_refresh
    import device_login
    import opencode_adapter
    import project_identity
    import provider_keys
    import settings_file
    import sign_in_again
    import usage
    from credential_profile import ProfileError, default_path, opened
    from project_registration import register
    from server_connection import ConnectionError, SignInExpired, account, models

# Commands that send something with the saved sign-in (ST29 "Sign out").
SIGNED_IN_COMMANDS = {"code", "keys", "whoami", "refresh", "logout",
                      "register-project", "models", "use", "usage"}

# Spec 004 ST17 (D150): the developer's switch for this repo's project.
SWITCHED = ("This repo's next tasks use {model}. "
            "Run `keeplane use --auto` to let Keeplane choose again.")
AUTO = "This repo's next tasks use the model Keeplane chooses."
# A developer can't switch to a model the project doesn't allow (keeplane #178).
# Wording decided by the associate product owner for task 009-07.
NOT_ALLOWED = ("{model} isn't allowed for this project. Nothing was saved. "
               "Choose one that `keeplane models` lists.")
SIGNED_OUT_USE = ("You're signed out of Keeplane, so nothing was saved. "
                  "Run `keeplane login` to sign in.")


def marked(issuer, project_id, credential, notify):
    """The allowed models, marking the one the next task uses (ST17)."""
    result = models(issuer, project_id, credential)
    allowed = {row["id"] for row in result["models"]}
    current, chosen_by, notices = coding.current_choice(
        issuer, project_id, credential, allowed)
    for notice in notices:
        notify(notice)
    for row in result["models"]:
        row["current"] = row["id"] == current
    result["chosen_by"] = chosen_by
    return result


def use_model(profile_path, project_id, model, name=None):
    """Save the switch for this repo's project, only for an allowed model."""
    with opened(profile_path) as profile:
        credential = profile.load()
        actor = account(credential.issuer, credential.access_token)
        if actor["id"] != credential.actor_id:
            raise ProfileError("The server account changed; sign in again.")
        if name:
            # Any repo works with no setup (D149): record it as `code` does.
            register(credential.issuer, project_id, name, credential.access_token)
        catalog = models(credential.issuer, project_id, credential.access_token)
    if model not in {row["id"] for row in catalog["models"]}:
        raise ConnectionError(NOT_ALLOWED.format(model=model), 403)
    settings_file.set_project_model(project_id, model)
    return SWITCHED.format(model=model)


def project_command(action, profile_path, project_id, name=None, notify=None):
    with opened(profile_path) as profile:
        credential = profile.load()
        actor = account(credential.issuer, credential.access_token)
        if actor["id"] != credential.actor_id:
            raise ProfileError("The server account changed; sign in again.")
        secrets = (credential.access_token, credential.refresh_token)

        def report(message):
            for secret in secrets:
                message = message.replace(secret, "[redacted]")
            if notify:
                notify(message)

        if action == "register-project":
            result = register(
                credential.issuer, project_id, name, credential.access_token
            )
        elif action == "models":
            if name:
                # Any repo works with no setup (D149): record it as `code` does.
                register(credential.issuer, project_id, name, credential.access_token)
            result = marked(credential.issuer, project_id, credential.access_token,
                            report)
        else:
            raise ValueError("Choose a project command")
        output = json.dumps(result, indent=2)
        for secret in secrets:
            output = output.replace(secret, "[redacted]")
        return output


def profile_path(given, *, create=False):
    """The profile to use: --profile, or the default one (ADR 030)."""
    if given:
        return given
    path = default_path()
    if create:
        # Only the default's own folder is made; a --profile folder must already exist.
        path.parent.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.parent.mkdir(mode=0o700)
        except FileExistsError:
            pass
    return str(path)


def repo_project(project_id, name=None, *, need_name=False):
    """--project when given, otherwise the project of the repo in this folder."""
    if project_id is not None and not need_name:
        return project_identity.resolve(Path.cwd(), project_id, "").id, None
    project = project_identity.resolve(Path.cwd(), project_id, name)
    return project.id, project.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login", help="Sign in through the browser")
    login.add_argument("--server", required=True)
    login.add_argument("--profile", help="Default: ~/.config/keeplane/account")
    login.add_argument("--timeout", type=int, default=120)
    login.add_argument("--device", action="store_true", help="Sign in using a code on another browser")
    init = commands.add_parser("init", help="Preview existing project instructions and settings")
    init_mode = init.add_mutually_exclusive_group(required=True)
    init_mode.add_argument("--preview", action="store_true")
    init_mode.add_argument("--apply", type=Path, metavar="PLAN", help="Confirm one saved root-instruction migration")
    init.add_argument("--directory", type=Path, default=Path.cwd())
    init.add_argument("--source", choices=("CLAUDE.md", "QWEN.md"))
    init.add_argument("--plan", type=Path, help="Save a selected instruction preview outside the repository")
    code = commands.add_parser(
        "code", help="Run a local coding turn through the protected gateway",
        description="Code in the repo in this folder. Every option has a default.")
    code.add_argument("--profile", help="Default: ~/.config/keeplane/account")
    code.add_argument("--project", help="Default: worked out from the repo")
    code.add_argument("--name", help="Default: the repo's remote path or folder name")
    code.add_argument("--model", help="This turn only. Default: your `keeplane use` "
                      "choice, then the model Keeplane picks for this project")
    code.add_argument("--runtime", help="Default: the settings file, then opencode on PATH")
    code.add_argument("--gateway", help="Default: the address your server gave at sign-in, ending in /v1")
    code.add_argument("--directory", type=Path, default=Path.cwd())
    code.add_argument("--timeout", type=float, default=300)
    code.add_argument("--instructions", action="append", default=[], type=Path)
    code.add_argument("--state-dir", type=Path)
    code.add_argument("--session")
    code.add_argument("prompt")
    keys = commands.add_parser("keys", help="Manage your server-held model provider keys")
    key_commands = keys.add_subparsers(dest="key_action", required=True)
    key_list = key_commands.add_parser("list", help="List allowed models and your saved key status")
    key_list.add_argument("--profile")
    key_list.add_argument("--project", help="Default: worked out from the repo")
    for action in ("set", "status", "check", "remove"):
        command = key_commands.add_parser(action)
        command.add_argument("--profile")
        command.add_argument("--model", required=True)
        if action == "set":
            command.add_argument("--key-stdin", action="store_true", help="Read the key from a pipe instead of the hidden prompt")
    for action, help_text in {
        "whoami": "Show the current account",
        "refresh": "Rotate this CLI credential pair once",
        "logout": "Revoke this CLI session and remove its local credential",
        "forget": "Remove only the local credential",
        "register-project": "Record your use of this repo's project",
        "models": "List the models this repo's project may use, marking the current one",
        "usage": "Show your own tokens and estimated cost per model, today and this month",
    }.items():
        command = commands.add_parser(action, help=help_text)
        command.add_argument("--profile", help="Default: ~/.config/keeplane/account")
        if action in {"register-project", "models"}:
            command.add_argument("--project", help="Default: worked out from the repo")
        if action == "register-project":
            command.add_argument("--name", help="Default: the repo's remote path or folder name")
    use = commands.add_parser(
        "use", help="Choose the model for this repo's next tasks",
        description="Save the model this repo's next tasks use, or let Keeplane choose.")
    use.add_argument("model", nargs="?", metavar="MODEL",
                     help="A model `keeplane models` lists")
    use.add_argument("--auto", action="store_true",
                     help="Clear your choice and let Keeplane choose")
    use.add_argument("--profile", help="Default: ~/.config/keeplane/account")
    use.add_argument("--project", help="Default: worked out from the repo")
    args = parser.parse_args()
    if args.command == "use" and (args.model is None) == (not args.auto):
        parser.error("Name one MODEL, or pass --auto.")
    try:
        if args.command != "init":
            args.profile = profile_path(args.profile, create=args.command == "login")
        # Clearing a switch is local, so it needs no sign-in.
        needs_sign_in = args.command in SIGNED_IN_COMMANDS and not (
            args.command == "use" and args.auto)
        if needs_sign_in and not sign_in_again.signed_in(args.profile):
            if args.command == "logout":
                print(sign_in_again.ALREADY_SIGNED_OUT)
                return 0
            print(SIGNED_OUT_USE if args.command == "use"
                  else sign_in_again.SIGNED_OUT_MESSAGES[args.command], file=sys.stderr)
            return 1
        if args.command == "init":
            if sys.version_info < (3, 11):
                print("Migration preview requires Python 3.11 or newer.", file=sys.stderr)
                return 2
            if args.apply or args.source or args.plan:
                if args.apply and (args.source or args.plan) or bool(args.source) != bool(args.plan):
                    parser.error("Use --preview with both --source and --plan, or --apply PLAN.")
                if __package__:
                    from . import migration_apply
                else:
                    import migration_apply
                try:
                    result = migration_apply.apply(args.directory, args.apply) if args.apply else migration_apply.review(args.directory, args.source, args.plan)
                except migration_apply.MigrationError as error:
                    print(str(error), file=sys.stderr)
                    return 2
                except (OSError, ValueError, TypeError, RecursionError):
                    print("Cannot safely complete this migration. Check the plan and repository files.", file=sys.stderr)
                    return 2
                print(json.dumps(result, indent=2))
                return 0
            if __package__:
                from .migration_preview import report
            else:
                from migration_preview import report
            return report(args.directory)
        elif args.command == "login":
            # An expired sign-in is replaced; one the server still accepts is refused.
            sign_in_again.clear_expired(args.profile)
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
        elif args.command == "use":
            project_id, name = repo_project(args.project)
            if args.auto:
                settings_file.set_project_model(project_id, None)
                output = AUTO
            else:
                output = use_model(args.profile, project_id, args.model, name)
        elif args.command == "usage":
            output = usage.show(args.profile)
        elif args.command == "keys":
            if args.key_action == "list":
                output = provider_keys.list_keys(args.profile, *repo_project(args.project))
            else:
                output = provider_keys.run(args.key_action, args.profile, args.model,
                                           key_stdin=getattr(args, "key_stdin", False))
        elif args.command == "code":
            def start():
                with opencode_adapter.termination_requested() as cancelled:
                    return coding.run(
                        args.profile, args.project, args.name, args.model, args.runtime,
                        args.directory, args.gateway, args.prompt, args.timeout,
                        cancelled=cancelled, instructions=args.instructions,
                        state_dir=args.state_dir, session=args.session,
                        notify=lambda message: print(message, file=sys.stderr),
                    )

            try:
                result = start()
            except SignInExpired as expired:
                # ST29, D190: in a terminal, offer to sign in again, then ask to start.
                result = sign_in_again.recover(expired, start, args.profile)
                if result is None:
                    return 1
            print(result.stdout, end="")
            print(result.stderr, end="", file=sys.stderr)
            return result.returncode
        else:
            project_id, name = repo_project(
                args.project, getattr(args, "name", None),
                need_name=args.command == "register-project")
            output = project_command(
                args.command, args.profile, project_id, name,
                notify=lambda message: print(message, file=sys.stderr))
        print(output)
    except SignInExpired as expired:
        print(sign_in_again.EXPIRED_NOT_SAVED if args.command == "use"
              else sign_in_again.expired_message(
                  expired, args.command, getattr(args, "key_action", None)),
              file=sys.stderr)
        return 1
    except (ProfileError, ConnectionError, project_identity.ProjectIdentityError,
            settings_file.SettingsError) as error:
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
