"""Send one prompt through the signed-in local preview (developer demo helper)."""

import argparse
import http.cookiejar
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


BASE = "http://127.0.0.1:3000"
PASSWORD = Path("/private/tmp/keeplane-accounts-trial/first-admin-password")


def post(opener, path, payload):
    request = Request(BASE + path, method="POST", data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json", "X-Keeplane-Action": "1"})
    with opener.open(request, timeout=120) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", help="Approved Keeplane model name, e.g. demo-qwen")
    parser.add_argument("prompt", help="Prompt to send through Keeplane and agentgateway")
    args = parser.parse_args()
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        post(opener, "/api/session", {"username": "first-admin",
                                        "password": PASSWORD.read_text().strip()})
        result = post(opener, "/api/ask", {"model": args.model, "prompt": args.prompt})
        print(result["answer"])
        opener.open(BASE + "/sign-out", timeout=10).close()
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
