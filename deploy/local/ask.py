"""Send one prompt through the signed-in local preview (developer demo helper)."""

import argparse
import http.cookiejar
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


BASE = os.environ.get("KEEPLANE_BASE_URL", "http://127.0.0.1:3000").rstrip("/")
LEGACY = Path("/private/tmp/keeplane-accounts-trial")
RUNTIME = Path(os.environ.get("KEEPLANE_RUNTIME_DIR", LEGACY if LEGACY.is_dir() else Path(__file__).resolve().parents[2] / ".keeplane/local"))
PASSWORD = RUNTIME / "first-admin-password"


def post(opener, path, payload):
    with opener.open(BASE + "/api/auth-options", timeout=10) as response:
        token = json.load(response)["csrf_token"]
    request = Request(BASE + path, method="POST", data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json", "X-Keeplane-Action": "1",
                               "Origin": BASE, "X-CSRFToken": token})
    with opener.open(request, timeout=120) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="Approved Keeplane model name, e.g. demo-qwen")
    parser.add_argument("prompt", help="Prompt to send through Keeplane and agentgateway")
    args = parser.parse_args()
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    signed_in = False
    try:
        post(opener, "/api/session", {"username": "first-admin",
                                        "password": PASSWORD.read_text().strip()})
        signed_in = True
        result = post(opener, "/api/ask", {"model": args.model, "prompt": args.prompt})
        print(result["answer"])
    except HTTPError as error:
        try:
            message = json.load(error).get("error", "Request failed")
        except (ValueError, AttributeError):
            message = "Request failed"
        print(f"Keeplane returned HTTP {error.code}: {message}", file=sys.stderr)
        return 1
    except (OSError, URLError, KeyError) as error:
        print(f"Local preview is unavailable or returned an invalid answer: {error}",
              file=sys.stderr)
        return 1
    finally:
        if signed_in:
            try:
                post(opener, "/sign-out", {})
            except (OSError, URLError, ValueError):
                print("Could not close the demo session; it will expire automatically.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
