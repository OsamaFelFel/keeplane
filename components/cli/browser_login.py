"""Browser sign-in using S256 PKCE, with the device code when no browser can open.

Spec 009 ST29 "No browser on the machine" (D161, ADR 028): over SSH, with no
display, with no browser to find, or when the browser fails to start, the CLI
signs in with the device code by itself, without ``--device``.
"""

import argparse
import base64
import hashlib
import http.client
import json
import math
import os
import re
import secrets
import socket
import ssl
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread, Timer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

if __package__:
    from .credential_profile import Credential, ProfileError, decode, opened
    from .server_connection import ConnectionError, NoRedirects, logout, origin, session
else:
    from credential_profile import Credential, ProfileError, decode, opened
    from server_connection import ConnectionError, NoRedirects, logout, origin, session

BROWSER = "Opening Keeplane sign-in in your browser."
NO_BROWSER = "No browser can open here, so sign in from another device."
NO_SERVER = (
    "Keeplane doesn't know your server yet. Run `keeplane login --server <address>`."
)
UNFINISHED = (
    "The sign-in in your browser didn't finish, so you aren't signed in. "
    "Run `keeplane login` to try again, "
    "or `keeplane login --device` to sign in from another device."
)


# 009-15: Keeplane was down or restarting (no answer, or a 5xx) when the CLI
# came to exchange the sign-in, so nothing was saved and trying again works.
UNAVAILABLE = (
    "Keeplane isn't available right now, so you aren't signed in. "
    "Run `keeplane login` to try again in a few minutes."
)


class BrowserUnavailable(ConnectionError):
    """The browser failed to start; nothing was sent to the server yet."""


class ServerUnavailable(ConnectionError):
    """No connection to the sign-in server, or a 5xx: nothing was changed there."""


class AnswerCutOff(ServerUnavailable):
    """The request reached the sign-in server but its answer was cut off.

    The server may have acted on it, so callers never resend an
    authorization code and never say that nothing changed.
    """


def no_browser(environ=None, platform=None, find=None):
    """Why no browser can open on this machine, or None when one may.

    A browser opened over SSH would open on the far machine, or not at all, and
    its loopback callback could never reach this CLI.
    """
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if any(environ.get(name) for name in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")):
        return "ssh"
    if environ.get("BROWSER"):
        return None  # The developer named a browser command; try it.
    if platform not in {"darwin", "win32", "cygwin"} and not (
        environ.get("DISPLAY") or environ.get("WAYLAND_DISPLAY")
    ):
        return "no display"
    try:
        (find or webbrowser.get)()
    except webbrowser.Error:
        return "no browser"
    return None


class CallbackServer(HTTPServer):
    """A socket timer also bounds clients that drip-feed HTTP headers."""

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(1)
        self.timer = Timer(
            max(0.001, min(2, self.deadline - time.monotonic())),
            self.close_connection,
            args=(connection,),
        )
        self.timer.daemon = True
        self.timer.start()
        return connection, address

    @staticmethod
    def close_connection(connection):
        try:
            connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        connection.close()

    def shutdown_request(self, connection):
        self.timer.cancel()
        super().shutdown_request(connection)

    def handle_error(self, request, client_address):
        pass  # Never print a callback URL, code or raw parser exception.


def authorization_code(server, *, timeout, browser):
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    result, launch = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            valid = False
            try:
                target = urlsplit(self.path)
                values = parse_qs(
                    target.query,
                    strict_parsing=True,
                    keep_blank_values=True,
                    max_num_fields=5,
                )
                valid = (
                    len(self.path) <= 4096
                    and not target.scheme
                    and not target.netloc
                    and target.path == "/callback"
                    and not target.fragment
                    and self.headers.get_all("Host")
                    == [listener.server_address[0] + ":" + str(listener.server_port)]
                    and all(len(value) == 1 for value in values.values())
                    and secrets.compare_digest(values.get("state", [""])[0], state)
                    and values.get("iss", [server])[0] == server
                )
                if valid and "code" in values and "error" not in values:
                    code = values["code"][0]
                    valid = re.fullmatch(r"[A-Za-z0-9_-]{16,200}", code) is not None
                    if valid:
                        result.append(code)
                elif valid and "error" in values and "code" not in values:
                    result.append(None)
                else:
                    valid = False
            except (ValueError, UnicodeError, TypeError):
                valid = False
            self.send_response(200 if valid else 400)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Return to the Keeplane CLI.\n")

    with CallbackServer(("127.0.0.1", 0), Handler) as listener:
        listener.deadline, listener.timeout = time.monotonic() + timeout, 0.1
        redirect = "http://127.0.0.1:" + str(listener.server_port) + "/callback"
        url = (
            server
            + "/oauth/authorize/?"
            + urlencode(
                {
                    "client_id": "keeplane-cli",
                    "response_type": "code",
                    "scope": "runtime",
                    "redirect_uri": redirect,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "state": state,
                }
            )
        )

        def open_browser():
            try:
                launch.append(browser(url))
            except Exception:  # noqa: BLE001 - OS browser failure must not expose raw details.
                launch.append(False)

        Thread(target=open_browser, daemon=True).start()
        while not result and time.monotonic() < listener.deadline:
            if launch and not launch[0]:
                raise BrowserUnavailable("The browser could not open.")
            listener.handle_request()
        # A browser that opened but timed out or was refused doesn't fall back.
        if not result or result[0] is None:
            raise ConnectionError(UNFINISHED)
        return {
            "grant_type": "authorization_code",
            "client_id": "keeplane-cli",
            "code": result[0],
            "code_verifier": verifier,
            "redirect_uri": redirect,
        }


class AuthorizationPending(ConnectionError):
    """Only the reviewed, non-secret device polling conditions."""

    def __init__(self, code):
        super().__init__("CLI access is waiting for approval.")
        self.code = code


def unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError
        result[name] = value
    return result


def exchange(server, form, *, allow_pending=False, timeout=10):
    request = Request(
        server + "/oauth/token/",
        data=urlencode(form).encode(),
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
                raise ConnectionError(
                    "The sign-in server returned an unexpected response."
                )
            raw = response.read(4097)

        data = json.loads(raw, object_pairs_hook=unique)
        if (
            len(raw) > 4096
            or not isinstance(data, dict)
            or not {
                "access_token",
                "refresh_token",
                "token_type",
                "scope",
                "expires_in",
            }
            <= data.keys()
            or not isinstance(data["token_type"], str)
            or data["token_type"].lower() != "bearer"
            or data["scope"] != "runtime"
            or type(data["expires_in"]) not in {int, float}
            or not math.isfinite(data["expires_in"])
            or data["expires_in"] <= 0
        ):
            raise ValueError
        # Reuse the exact credential alphabet without inventing an account ID.
        checked = decode(
            {
                "format": "keeplane-credential-v1",
                "issuer": server,
                "actor_id": "00000000-0000-0000-0000-000000000000",
                "access_token": data["access_token"],
                "refresh_token": data["refresh_token"],
            }
        )
        return checked.access_token, checked.refresh_token
    except HTTPError as error:
        try:
            if (
                allow_pending
                and error.code == 400
                and error.headers.get_content_type() == "application/json"
            ):
                raw = error.read(4097)
                if len(raw) <= 4096:
                    data = json.loads(raw, object_pairs_hook=unique)
                    if isinstance(data, dict) and data.get("error") in {
                        "authorization_pending",
                        "slow_down",
                    }:
                        raise AuthorizationPending(data["error"])
        except (OSError, ValueError, RecursionError, TypeError):
            pass
        finally:
            error.close()
        if error.code >= 500:
            raise ServerUnavailable(
                "The sign-in server is unavailable.", error.code
            ) from None
        raise ConnectionError(
            "The sign-in server refused the exchange.", error.code
        ) from None
    except URLError as error:
        if isinstance(error.reason, ssl.SSLError):
            # A certificate or TLS problem, not an outage.
            raise ConnectionError(
                "Cannot complete sign-in securely; no credential was saved."
            ) from None
        # urllib wraps only failures to connect and send: nothing reached
        # the server, so nothing changed there.
        raise ServerUnavailable(
            "Cannot complete sign-in securely; no credential was saved."
        ) from None
    except (OSError, http.client.HTTPException):
        # The request was sent but its answer was cut off.
        raise AnswerCutOff(
            "Cannot complete sign-in securely; no credential was saved."
        ) from None
    except (ValueError, OverflowError, RecursionError, ProfileError):
        raise ConnectionError(
            "Cannot complete sign-in securely; no credential was saved."
        ) from None


def save_login(profile, server, access, refresh, *, client_id="keeplane-cli"):
    try:
        # Save the gateway address the server gives (task 009-02b); none if it has none.
        actor, gateway = session(server, access)
        profile.save(
            Credential(server, actor["id"], access, refresh, client_id, gateway)
        )
    except BaseException:
        # A later admission/storage failure must not silently leave a valid pair.
        try:
            logout(server, access)
        except (ConnectionError, ValueError):
            raise ConnectionError(
                "Sign-in was not saved reliably; server revocation could not be confirmed."
            ) from None
        raise
    try:
        # A bad kept address is replaced only once sign-in has succeeded.
        profile.replace_kept_server(server)
    except (OSError, ProfileError):
        # Signed in all the same; the old file stays as it was (atomic write).
        pass


def login(server, path, *, timeout=120, browser=None, announce=print):
    """Sign in through the browser, or with the device code when none can open.

    Returns "browser" or "device", the way the developer signed in.
    """
    server = origin(server)
    if not 1 <= timeout <= 300:
        raise ConnectionError("Choose a browser wait from one to 300 seconds.")
    if browser is None and no_browser():
        return device(server, path, timeout=timeout, announce=announce)
    try:
        with opened(path, create=True) as profile:
            if "credential.json" in os.listdir(profile.directory):
                raise ProfileError(
                    "This profile is signed in. Log out or forget it first."
                )
            announce(BROWSER)
            form = authorization_code(
                server, timeout=timeout, browser=browser or webbrowser.open
            )
            try:
                access, refresh = exchange(server, form)
            except ServerUnavailable:
                # The code is used once; a new sign-in starts from the browser.
                raise ConnectionError(UNAVAILABLE) from None
            save_login(profile, server, access, refresh)
    except BrowserUnavailable:
        # The listener is closed and the profile unlocked before the device code.
        return device(server, path, timeout=timeout, announce=announce)
    return "browser"


def device(server, path, *, timeout, announce):
    if __package__:
        from . import device_login
    else:
        import device_login

    announce(NO_BROWSER)
    device_login.login(server, path, timeout=timeout, announce=announce)
    return "device"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    try:
        login(args.server, args.profile, timeout=args.timeout)
    except (ConnectionError, ProfileError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Sign-in cancelled.", file=sys.stderr)
        return 130
    except (OSError, ValueError, TypeError):
        print("Sign-in could not complete securely.", file=sys.stderr)
        return 1
    print("Signed in to Keeplane.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
