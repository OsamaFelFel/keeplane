"""Check a fixed Personal provider without reading or sending anybody's key."""

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


def probe_request(resource, *, allow_loopback_http=False):
    if not isinstance(resource, dict) or set(resource) - {
        "id",
        "name",
        "provider",
        "params",
        "auth",
    }:
        raise ValueError("Unsupported Personal provider definition")
    provider, params = resource.get("provider"), resource.get("params")
    auth = resource.get("auth")
    if (
        provider not in ("openAI", "anthropic")
        or (auth is not None and (type(auth) is not dict or auth))
        or not isinstance(params, dict)
        or set(params) - {"model", "baseUrl"}
        or not isinstance(params.get("model"), str)
        or not 0 < len(params["model"]) <= 256
        or ("id" in resource and resource["id"] != resource.get("name"))
    ):
        raise ValueError("Use a fixed cloud model without a shared key")
    base = params.get(
        "baseUrl",
        {
            "openAI": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com/v1",
        }[provider],
    )
    if (
        not isinstance(base, str)
        or not 0 < len(base) <= 2048
        or any(ord(char) < 33 or ord(char) > 126 for char in base)
    ):
        raise ValueError("Use an approved HTTPS provider address")
    url = urlsplit(base)
    loopback = (
        allow_loopback_http is True
        and url.scheme == "http"
        and url.hostname in ("localhost", "127.0.0.1", "::1")
    )
    if (
        (url.scheme != "https" and not loopback)
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
    ):
        raise ValueError("Use an approved HTTPS provider address")
    _ = url.port
    suffix = "/chat/completions" if provider == "openAI" else "/messages"
    return {
        "provider": provider,
        "model": params["model"],
        "url": base.rstrip("/") + suffix,
    }


def provider_answers(resource, *, timeout=8, allow_loopback_http=False):
    if not 0 < timeout <= 10:
        raise ValueError("Choose a provider check deadline up to ten seconds")
    try:
        config = probe_request(resource, allow_loopback_http=allow_loopback_http)
    except (ValueError, TypeError):
        return False
    try:
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                str(Path(__file__).with_name("provider_probe_http.py")),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError:
        return False
    try:
        process.communicate(json.dumps(config).encode(), timeout=timeout)
        return process.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)
        process.stdin.close()
