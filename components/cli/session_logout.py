"""Revoke an experimental Keeplane session at the server."""

import argparse
import getpass
import os
import sys

if __package__:
    from .server_connection import ConnectionError, logout
else:
    from server_connection import ConnectionError, logout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    args = parser.parse_args()
    credential = os.environ.pop("KEEPLANE_SESSION_CREDENTIAL", None)
    try:
        if credential is None:
            if not sys.stdin.isatty():
                raise ConnectionError("Set KEEPLANE_SESSION_CREDENTIAL for noninteractive use.")
            credential = getpass.getpass("Keeplane test session to revoke: ")
        logout(args.server, credential)
    except ConnectionError as error:
        print(str(error), file=sys.stderr)
        return 1
    except ValueError:
        print("Check the Keeplane server address.", file=sys.stderr)
        return 1
    print("Keeplane session revoked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
