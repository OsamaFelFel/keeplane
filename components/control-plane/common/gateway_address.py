"""The gateway address the installer gives developers' CLIs (ADR 030, Spec 009 ST30).

Keeplane never works this address out from a request: the installer sets
KEEPLANE_GATEWAY_PUBLIC_URL, the preview and the Helm chart set it for their own
protected gateway, and an unset value means Keeplane doesn't know it.
"""

from urllib.parse import urlsplit

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def public_gateway_url(value):
    """None when unset, else the address in the form the CLI uses, or RuntimeError.

    It must end in /v1, have no user name, password, query or fragment, and use
    HTTPS unless its host is this machine: the rules `keeplane code --gateway`
    applies, so the CLI accepts every address the server gives.
    """
    if value is None or value == "":
        return None
    problem = "KEEPLANE_GATEWAY_PUBLIC_URL must be the gateway address developers use, ending in /v1"
    if not isinstance(value, str) or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise RuntimeError(problem)
    url = urlsplit(value)
    try:
        port = url.port
    except ValueError:
        raise RuntimeError(problem) from None
    if (
        url.scheme not in {"https", "http"}
        or not url.hostname
        or port == 0
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or "?" in value
        or "#" in value
        or url.path.rstrip("/") != "/v1"
        or url.path.count("/") > 2
    ):
        raise RuntimeError(problem)
    if url.scheme == "http" and url.hostname not in LOOPBACK:
        raise RuntimeError(
            "KEEPLANE_GATEWAY_PUBLIC_URL must use HTTPS unless the gateway is on this machine"
        )
    host = "[" + url.hostname + "]" if ":" in url.hostname else url.hostname
    default = 443 if url.scheme == "https" else 80
    suffix = "" if port is None or port == default else ":" + str(port)
    return url.scheme + "://" + host + suffix + "/v1"
