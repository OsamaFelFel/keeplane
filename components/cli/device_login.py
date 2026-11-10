"""Device-code sign-in, with ``--device`` or when no browser can open (ST29).

Approval codes stay in memory until the token exchange. While waiting, a
Keeplane that doesn't answer, or answers with a 5xx, is asked again at the
next interval: an app or database restart doesn't end the sign-in.
"""

import json
import math
import os
import re
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

if __package__:
    from .browser_login import (
        UNAVAILABLE,
        AuthorizationPending,
        ServerUnavailable,
        exchange,
        save_login,
        unique,
    )
    from .credential_profile import ProfileError, opened
    from .server_connection import ConnectionError, NoRedirects, origin
else:
    from browser_login import (
        UNAVAILABLE,
        AuthorizationPending,
        ServerUnavailable,
        exchange,
        save_login,
        unique,
    )
    from credential_profile import ProfileError, opened
    from server_connection import ConnectionError, NoRedirects, origin

CLIENT_ID = "keeplane-cli-device"


def start(server, *, timeout):
    request = Request(
        server + "/oauth/device/",
        data=urlencode({"client_id": CLIENT_ID, "scope": "runtime"}).encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with build_opener(ProxyHandler({}), NoRedirects()).open(
            request, timeout=timeout
        ) as response:
            if (
                response.status != 200
                or response.headers.get_content_type() != "application/json"
            ):
                raise ValueError
            raw = response.read(4097)
        data = json.loads(raw, object_pairs_hook=unique)
        if (
            len(raw) > 4096
            or not isinstance(data, dict)
            or data.get("verification_uri") != server + "/oauth/confirm-device/"
            or not isinstance(data.get("user_code"), str)
            or not re.fullmatch(r"[0-9A-V]{8}", data["user_code"])
            or not isinstance(data.get("device_code"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", data["device_code"])
        ):
            raise ValueError
        interval = data.get("interval", 5)
        if type(interval) is not int or interval < 1:
            raise ValueError
        for value in (data.get("expires_in"),):
            if (
                type(value) not in {int, float}
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError
        return data["user_code"], data["device_code"], interval, data["expires_in"]
    except HTTPError as error:
        error.close()
        if error.code >= 500:
            raise ConnectionError(UNAVAILABLE) from None
        raise ConnectionError("Keeplane refused device sign-in; retry later.") from None
    except (URLError, OSError):
        # Nothing was started on the server.
        raise ConnectionError(UNAVAILABLE) from None
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ConnectionError("Cannot start device sign-in securely.") from None


def login(server, path, *, timeout=120, announce=print):
    server = origin(server)
    if not 1 <= timeout <= 300:
        raise ConnectionError("Choose a sign-in wait from one to 300 seconds.")
    deadline = monotonic() + timeout
    with opened(path, create=True) as profile:
        if "credential.json" in os.listdir(profile.directory):
            raise ProfileError("This profile is signed in. Log out or forget it first.")
        code, device_code, interval, expires = start(server, timeout=min(10, timeout))
        deadline = min(deadline, monotonic() + expires)
        announce(
            "Open " + server + "/oauth/confirm-device/ and enter code " + code + "."
        )
        while True:
            if interval >= deadline - monotonic():
                raise ConnectionError(
                    "Device sign-in timed out; no credential was saved."
                )
            sleep(interval)
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ConnectionError(
                    "Device sign-in timed out; no credential was saved."
                )
            try:
                access, refresh = exchange(
                    server,
                    {
                        "client_id": CLIENT_ID,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "device_code": device_code,
                    },
                    allow_pending=True,
                    timeout=min(10, remaining),
                )
            except AuthorizationPending as pending:
                if pending.code == "slow_down":
                    interval += 5
                continue
            except ServerUnavailable:
                # 009-15: Keeplane is restarting. The code waits in its
                # database, so keep asking until it answers or time runs out.
                continue
            save_login(profile, server, access, refresh, client_id=CLIENT_ID)
            return
