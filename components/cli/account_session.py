"""Check or sign out an explicit private Keeplane credential profile."""

import argparse
import json
import os
import sys

if __package__:
    from .credential_profile import ProfileError, opened
    from .server_connection import ConnectionError, account, logout
else:
    from credential_profile import ProfileError, opened
    from server_connection import ConnectionError, account, logout


NOTHING_TO_FORGET = (
    "Keeplane has no saved sign-in or server address, so there's nothing to forget."
)
REMOVED_SERVER = (
    "Removed the saved server address. "
    "Run `keeplane login --server <address>` to sign in."
)
REMOVED_UNUSABLE_SERVER = (
    "Removed the server address Keeplane couldn't use. "
    "Run `keeplane login --server <address>` to sign in."
)


def run(action, path):
    with opened(path) as profile:
        if action == "forget":
            if "credential.json" not in os.listdir(profile.directory):
                # Signed out: forget the kept server address too.
                removed = profile.remove_server()
                if removed == "unusable":
                    return REMOVED_UNUSABLE_SERVER
                if removed == "usable":
                    return REMOVED_SERVER
                return NOTHING_TO_FORGET
            profile.forget()
            return "Local credential removed; server revocation was not requested."
        credential = profile.load()
        if action == "whoami":
            result = account(credential.issuer, credential.access_token)
            if result["id"] != credential.actor_id:
                raise ProfileError("The server account changed; sign in again.")
            output = json.dumps(result, indent=2)
            for secret in (credential.access_token, credential.refresh_token):
                output = output.replace(secret, "[redacted]")
            return output
        if action != "logout":
            raise ProfileError("Choose whoami, logout or forget.")
        try:
            logout(credential.issuer, credential.access_token)
        except ConnectionError as error:
            if error.status != 401:
                raise
        profile.forget()
        return "Keeplane session withdrawn; local credential removed."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["whoami", "logout", "forget"])
    parser.add_argument("--profile", required=True)
    args = parser.parse_args()
    try:
        print(run(args.action, args.profile))
    except (ProfileError, ConnectionError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (ValueError, TypeError):
        print("The credential profile is unavailable.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
