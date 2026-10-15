"""Sibling client with only its synthetic developer credential and project ID."""

import json
import os
import sys
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
    + ":5000"
    + options.get("path", "/v1/chat/completions"),
    data=json.dumps(body).encode(),
    headers=headers,
)
try:
    with urlopen(request, timeout=5) as response:
        response.read()
        status = response.status
except HTTPError as error:
    error.read()
    status = error.code
print(json.dumps(status))
