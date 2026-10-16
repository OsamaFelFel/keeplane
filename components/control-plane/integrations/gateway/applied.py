"""Private, bounded reads of the selected native gateway's applied configuration."""

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

APPLIED_PATH = "/internal/keeplane/applied"
MAX_APPLIED_BYTES = 1024 * 1024


class AppliedStateUnavailable(ValueError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def private_applied_route(api_key):
    """Only the existing private runtime credential can read loopback admin state."""
    if (
        not isinstance(api_key, dict)
        or api_key.get("mode") != "strict"
        or not api_key.get("keys")
    ):
        raise AppliedStateUnavailable("Private operator authentication is required")
    return {
        "gateways": "default",
        "name": "keeplane-applied-state",
        "matches": [{"method": "GET", "path": {"exact": APPLIED_PATH}}],
        "backends": [{"host": "127.0.0.1:15000"}],
        "policies": {
            "apiKey": deepcopy(api_key),
            "urlRewrite": {"path": {"full": "/config_dump"}},
        },
    }


def read_applied(gateway):
    """Use a 3-second socket timeout, bounded body, no redirect and no retry."""
    try:
        if any(ord(char) < 33 or ord(char) > 126 for char in gateway.base_url):
            raise ValueError()
        origin = urlsplit(gateway.base_url)
        if (
            origin.scheme not in ("http", "https")
            or not origin.hostname
            or origin.username is not None
            or origin.password is not None
            or origin.path
            or origin.query
            or origin.fragment
        ):
            raise ValueError()
        path = Path(gateway.runtime_key_file)
        if not path.is_absolute():
            raise ValueError()
        with path.open("rb") as source:
            raw = source.read(259)
        if len(raw) > 258 or not re.fullmatch(rb"[A-Za-z0-9_-]{32,256}", raw.strip()):
            raise ValueError()
        request = Request(
            gateway.base_url + APPLIED_PATH,
            headers={"Authorization": "Bearer " + raw.strip().decode("ascii")},
        )
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=3) as response:
            if (
                response.status != 200
                or response.headers.get_content_type() != "application/json"
            ):
                raise ValueError()
            body = response.read(MAX_APPLIED_BYTES + 1)
        if len(body) > MAX_APPLIED_BYTES:
            raise ValueError()
        return json.loads(body, object_pairs_hook=unique_pairs)
    except HTTPError as error:
        error.close()
        raise AppliedStateUnavailable(
            "Applied runtime configuration is unavailable"
        ) from None
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        raise AppliedStateUnavailable(
            "Applied runtime configuration is unavailable"
        ) from None


def unique_pairs(pairs):
    value = {}
    for key, row in pairs:
        if key in value:
            raise ValueError()
        value[key] = row
    return value


def applied_fingerprint(value):
    """Bind the complete dump, except validated request measurements."""
    try:
        if not isinstance(value, dict) or set(value) != {
            "workloads",
            "services",
            "binds",
            "routes",
            "policies",
            "backends",
            "models",
            "version",
            "config",
        }:
            raise ValueError()
        result = deepcopy(value)
        for backend in result["backends"]:
            ai = backend.get("backend", {}).get("ai")
            if ai is None:
                continue
            for provider in ai["target"]["providers"]:
                for endpoint in provider["active"].values():
                    info = endpoint["info"]
                    health = info["health"]
                    failures = info["consecutiveFailures"]
                    if (
                        type(health) not in (int, float)
                        or not 0 <= health <= 1  # Also rejects NaN and infinities.
                        or type(failures) is not int
                        or not 0 <= failures <= 2**64 - 1
                    ):
                        raise ValueError()
                    # These change when requests finish. Eviction state, membership,
                    # capacity, destinations, policies and unknown fields stay bound.
                    for field in (
                        "requestLatency",
                        "pendingRequests",
                        "totalRequests",
                        "health",
                        "consecutiveFailures",
                    ):
                        del info[field]
        canonical = json.dumps(
            result, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        return hashlib.sha256(canonical.encode()).hexdigest()
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
        raise AppliedStateUnavailable(
            "Applied runtime configuration is malformed"
        ) from None
