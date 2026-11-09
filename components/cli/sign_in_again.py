"""Say why nothing was sent when the sign-in has expired or is gone, and offer to sign in again.

Spec 009 ST29 "The sign-in has expired" and "Sign out" (D190, ADR 028). A 401
from the server or the gateway means the sign-in has expired: nothing more is
sent. In a terminal the developer may sign in again with the saved server and
then choose to start the task; in scripts the CLI exits 1 and names
``keeplane login``. A profile with no credential is signed out, with no offer.
"""

import sys
from pathlib import Path

if __package__:
    from . import browser_login, device_login
    from .credential_profile import ProfileError, opened
    from .server_connection import (
        SIGN_IN_AGAIN,
        ConnectionError,
        SignInExpired,
        account,
    )
else:
    import browser_login
    import device_login
    from credential_profile import ProfileError, opened
    from server_connection import SIGN_IN_AGAIN, ConnectionError, SignInExpired, account

SIGNED_OUT = (
    "You're signed out of Keeplane, so nothing was sent. "
    "Run `keeplane login` to sign in."
)
OFFER = "Sign in again now? [Y/n] "
START = "Signed in. Start the task now? [Y/n] "
BROWSER = "Opening Keeplane sign-in in your browser."


def signed_in(path):
    """False when the profile holds no credential: never signed in, or signed out."""
    return (Path(path).expanduser() / "credential.json").exists()


def in_terminal(stdin=None, stderr=None):
    stdin, stderr = stdin or sys.stdin, stderr or sys.stderr
    try:
        return stdin.isatty() and stderr.isatty()
    except (AttributeError, ValueError, OSError):
        return False


def ask(question, *, stdin=None, stderr=None):
    """Yes for Enter, y or yes; anything else, or no answer at all, is no."""
    stdin, stderr = stdin or sys.stdin, stderr or sys.stderr
    stderr.write(question)
    stderr.flush()
    answer = stdin.readline()
    if not answer:
        stderr.write("\n")
        return False
    return answer.strip().lower() in {"", "y", "yes"}


def clear_expired(path):
    """Remove the local credential only once its server says it has expired.

    Returns the saved server and sign-in client, or None when there is nothing
    saved. A credential the server still accepts, or a server that can't be
    reached, is kept: sign-in then refuses it as before.
    """
    if not signed_in(path):
        return None
    with opened(path) as profile:
        credential = profile.load()
        try:
            account(credential.issuer, credential.access_token)
        except SignInExpired:
            # The server refused it, so no revocation is possible or needed.
            profile.forget()
        except ConnectionError:
            pass
        return credential.issuer, credential.client_id


def sign_in(path, *, timeout=120, announce=None):
    """Sign in again with the saved server, the same way as last time."""
    announce = announce or (lambda message: print(message, file=sys.stderr))
    saved = clear_expired(path)
    if saved is None:
        raise ProfileError(SIGNED_OUT)
    server, client_id = saved
    if client_id == device_login.CLIENT_ID:
        device_login.login(server, path, timeout=timeout, announce=announce)
    else:
        announce(BROWSER)
        browser_login.login(server, path, timeout=timeout)


def recover(expired, start, path, *, stdin=None, stdout=None, stderr=None, timeout=120):
    """Handle an expired sign-in for a task; return the new run or None to exit 1.

    ``start`` runs the task again. It is called only after the developer signed
    in again and said yes; an expired sign-in on that run is not offered again.
    """
    stdout, stderr = stdout or sys.stdout, stderr or sys.stderr
    shown(expired, stdout, stderr)
    if not in_terminal(stdin, stderr):
        stderr.write(str(expired) + "\n")
        return None
    if not ask(expired.notice + " " + OFFER, stdin=stdin, stderr=stderr):
        stderr.write(SIGN_IN_AGAIN + "\n")
        return None
    sign_in(
        path, timeout=timeout, announce=lambda message: stderr.write(message + "\n")
    )
    if not ask(START, stdin=stdin, stderr=stderr):
        stderr.write(SIGN_IN_AGAIN + "\n")
        return None
    try:
        return start()
    except SignInExpired as again:
        shown(again, stdout, stderr)
        raise ConnectionError(str(again), 401) from None


def shown(expired, stdout, stderr):
    """Steps that already went out stay visible above the notice."""
    if expired.result is not None:
        stdout.write(expired.result.stdout)
        stderr.write(expired.result.stderr)
