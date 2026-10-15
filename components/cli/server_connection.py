"""List server-authorized project models using an experimental session transport."""

import argparse
import getpass
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid


LIMIT = 1024 * 1024


class ConnectionError(Exception):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def request(server, path, credential, *, method="GET", expected=200, payload=None):
    url = urlsplit(server)
    if (url.scheme not in {"https", "http"} or not url.hostname
            or url.username or url.password or url.query or url.fragment
            or url.path not in {"", "/"}):
        raise ConnectionError("Use a server origin without a path, credentials or query parameters.")
    if url.scheme == "http" and url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ConnectionError("Use HTTPS for a server outside this machine.")
    if not isinstance(credential, str) or re.fullmatch(r"[A-Za-z0-9._~-]{1,4096}", credential) is None:
        raise ConnectionError("Supply an opaque Keeplane session credential.")
    if not path.startswith("/api/runtime/") or "?" in path or "#" in path:
        raise ConnectionError("Use a supported runtime route.")
    outgoing = Request(
        server.rstrip("/") + path, method=method,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + credential, "Accept": "application/json"},
    )
    if payload is not None:
        outgoing.add_header("Content-Type", "application/json")
    # No ambient proxy, cookies, browser password store or redirect can carry the credential elsewhere.
    opener = build_opener(ProxyHandler({}), NoRedirects())
    try:
        with opener.open(outgoing, timeout=10) as response:
            if response.status != expected or (expected != 204 and response.headers.get_content_type() != "application/json"):
                raise ConnectionError("The server returned an unexpected response.")
            body = response.read(LIMIT + 1)
    except HTTPError as error:
        error.close()
        messages = {400: "The server refused these request details.",
                    401: "The Keeplane session is unavailable or expired.",
                    403: "The requested action is unavailable.", 503: "Keeplane is temporarily unavailable; retry later."}
        raise ConnectionError(messages.get(error.code, "The server refused this action.")) from None
    except (URLError, OSError, ValueError):
        raise ConnectionError("Cannot reach Keeplane securely; check the server and certificate configuration.") from None
    if len(body) > LIMIT:
        raise ConnectionError("The server response exceeds the supported size.")
    return body


def logout(server, credential):
    """Revoke only the supplied current session; never downgrade to cookie auth."""
    request(server, "/api/runtime/session", credential, method="DELETE", expected=204)


def models(server, project_id, credential):
    try:
        project_id = str(uuid.UUID(str(project_id)))
    except (ValueError, TypeError, AttributeError):
        raise ConnectionError("Use a valid project UUID.") from None
    body = request(server, "/api/runtime/projects/" + project_id + "/models", credential)
    try:
        data = json.loads(body)
        if not isinstance(data, dict) or set(data) != {"project_id", "models"}:
            raise ValueError
        if data["project_id"] != project_id or not isinstance(data["models"], list):
            raise ValueError
        ids = []
        for row in data["models"]:
            if not isinstance(row, dict) or set(row) != {"id"} or not isinstance(row["id"], str) or not 0 < len(row["id"]) <= 256:
                raise ValueError
            ids.append(row["id"])
        if len(set(ids)) != len(ids):
            raise ValueError
    except (ValueError, UnicodeError, RecursionError):
        raise ConnectionError("The server returned an invalid model catalog.") from None
    return {"project_id": project_id, "models": [{"id": value} for value in sorted(ids)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    credential = os.environ.pop("KEEPLANE_SESSION_CREDENTIAL", None)
    try:
        if credential is None:
            if not sys.stdin.isatty():
                raise ConnectionError("Set KEEPLANE_SESSION_CREDENTIAL for noninteractive use.")
            credential = getpass.getpass("Keeplane test session credential: ")
        result = models(args.server, args.project, credential)
    except ConnectionError as error:
        print(str(error), file=sys.stderr)
        return 1
    except ValueError:
        # URL parser errors may contain input; never print raw exception text.
        print("Model discovery failed. Check the server, session and project; no credential was saved.", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2).replace(credential, "[redacted]"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
