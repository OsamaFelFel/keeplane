"""Sibling client with only its synthetic developer credential and project ID."""

import json
import os
import sys
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

credential = json.loads(Path("/client/credential").read_text())
options = json.loads(sys.argv[1])
headers = {
    "Authorization": "Bearer " + credential["token"],
    "Content-Type": "application/json",
    "X-Keeplane-Project-ID": credential["project"],
    "X-Keeplane-Gateway-Credential": "client-cannot-choose-this",
}
headers.update(options.get("headers", {}))
body = options.get(
    "body",
    {
        "model": "private",
        "messages": [
            {"role": "user", "content": "synthetic prompt, not authorization metadata"}
        ],
    },
)
request = Request(
    "http://"
    + os.environ.get("FIXTURE_GATEWAY_HOST", "gateway")
    + ":"
    + str(options.get("port", 5000))
    + options.get("path", "/v1/chat/completions"),
    data=json.dumps(body).encode(),
    headers=headers,
)
try:
    with urlopen(request, timeout=options.get("timeout", 5)) as response:
        incomplete = False
        try:
            raw = response.read(65537)
        except (IncompleteRead, ConnectionError, TimeoutError) as error:
            # Only protocol checks expect a stream that ends early.
            if not options.get("observe_protocol"):
                raise
            raw, incomplete = getattr(error, "partial", b""), True
        if len(raw) > 65536:
            raise RuntimeError("Disposable protocol response is too large")
        status = response.status
        if options.get("observe_credentials"):
            print(
                json.dumps(
                    {
                        "status": status,
                        "authorization_returned": "Authorization" in response.headers,
                    }
                )
            )
            raise SystemExit(0)
        if options.get("observe_protocol"):
            print(
                json.dumps(
                    {
                        "status": status,
                        "content_type": response.headers.get("Content-Type"),
                        "body": raw.decode("utf-8", "replace"),
                        "incomplete": incomplete,
                    }
                )
            )
            raise SystemExit(0)
except HTTPError as error:
    error.read()
    status = error.code
    if options.get("observe_credentials"):
        print(
            json.dumps(
                {
                    "status": status,
                    "authorization_returned": "Authorization" in error.headers,
                }
            )
        )
        raise SystemExit(0)
print(json.dumps(status))
