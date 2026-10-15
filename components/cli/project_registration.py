"""Record project use with explicit context; no repository changes or onboarding."""

import argparse
import getpass
import json
import os
import sys
import uuid

if __package__:
    from .server_connection import ConnectionError, request
else:
    from server_connection import ConnectionError, request


def register(server, project_id, name, credential):
    try:
        project_id = str(uuid.UUID(str(project_id)))
    except (ValueError, TypeError, AttributeError):
        raise ConnectionError("Use a valid project UUID.") from None
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120 or not name.strip().isprintable():
        raise ConnectionError("Use a printable project name up to 120 characters.")
    body = request(server, "/api/runtime/projects", credential, method="POST",
                   payload={"project_id": project_id, "name": name})
    try:
        result = json.loads(body)
        if not isinstance(result, dict) or set(result) != {"project_id", "name"}:
            raise ValueError
        if result["project_id"] != project_id or not isinstance(result["name"], str) or not 1 <= len(result["name"]) <= 120:
            raise ValueError
        if not result["name"].isprintable():
            raise ValueError
    except (ValueError, UnicodeError, RecursionError):
        raise ConnectionError("The server returned invalid project metadata.") from None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    credential = os.environ.pop("KEEPLANE_SESSION_CREDENTIAL", None)
    try:
        if credential is None:
            if not sys.stdin.isatty():
                raise ConnectionError("Set KEEPLANE_SESSION_CREDENTIAL for noninteractive use.")
            credential = getpass.getpass("Keeplane test session credential: ")
        result = register(args.server, args.project, args.name, credential)
    except ConnectionError as error:
        print(str(error), file=sys.stderr)
        return 1
    except ValueError:
        print("Check the Keeplane server address.", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2).replace(credential, "[redacted]"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
