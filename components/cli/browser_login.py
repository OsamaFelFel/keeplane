"""Experimental browser sign-in using S256 PKCE and an explicit private profile."""

import argparse
import base64
import hashlib
import json
import math
import os
import re
import secrets
import socket
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
    from .server_connection import ConnectionError, NoRedirects, account, logout, origin
else:
    from credential_profile import Credential, ProfileError, decode, opened
    from server_connection import ConnectionError, NoRedirects, account, logout, origin


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
                raise ConnectionError(
                    "The browser could not open. Retry on a machine with a browser."
                )
            listener.handle_request()
        if not result:
            raise ConnectionError("Browser sign-in timed out; no credential was saved.")
        if result[0] is None:
            raise ConnectionError(
                "Browser sign-in was refused; no credential was saved."
            )
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
        raise ConnectionError("The sign-in server refused the exchange.") from None
    except (URLError, OSError, ValueError, OverflowError, RecursionError, ProfileError):
        raise ConnectionError(
            "Cannot complete sign-in securely; no credential was saved."
        ) from None


def save_login(profile, server, access, refresh, *, client_id="keeplane-cli"):
    try:
        actor = account(server, access)
        profile.save(Credential(server, actor["id"], access, refresh, client_id))
    except BaseException:
        # A later admission/storage failure must not silently leave a valid pair.
        try:
            logout(server, access)
        except (ConnectionError, ValueError):
            raise ConnectionError(
                "Sign-in was not saved reliably; server revocation could not be confirmed."
            ) from None
        raise


def login(server, path, *, timeout=120, browser=None):
    server = origin(server)
    if not 1 <= timeout <= 300:
        raise ConnectionError("Choose a browser wait from one to 300 seconds.")
    with opened(path, create=True) as profile:
        if "credential.json" in os.listdir(profile.directory):
            raise ProfileError("This profile is signed in. Log out or forget it first.")
        form = authorization_code(
            server, timeout=timeout, browser=browser or webbrowser.open
        )
        access, refresh = exchange(server, form)
        save_login(profile, server, access, refresh)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    try:
        print("Opening Keeplane sign-in in your browser.")
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
