"""Read the mounted database password on every new connection.

Kubernetes updates a mounted Secret file in place, so a process that read the
password once at start would keep using the old one after a rotation. The app
opens a new database connection for every request, so reading the file at
each connect is enough to pick up a rotated password without a restart.

PostgreSQL holds one password per role, and the file reaches each pod on its
own schedule. To let a rotation finish without refused requests, the documented
order is: write the new password to the Secret, wait until every pod reads it,
then change the role's password. While the role still has the old password,
a process keeps using the last password the database accepted, and logs once
that the new one was refused. As soon as the database accepts the password in
the file, that becomes the only one used. Nothing here ever uses a password the
database has not accepted, writes a password anywhere, or logs one.
"""

import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)


class DatabasePasswordUnavailable(OSError):
    pass


def read_password(path):
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        value = ""
    if not value:
        raise DatabasePasswordUnavailable("The database password file is empty or unreadable")
    return value


class RotatingPassword:
    """The password to try for a new connection, and the one last accepted."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._accepted = None
        self._previous_in_use = False

    @property
    def previous_in_use(self):
        """True while the database still refuses the password in the file."""
        with self._lock:
            return self._previous_in_use

    def connect(self, open_connection, refused):
        """Open a connection with the file's password, or the last accepted one.

        `open_connection(password)` opens one connection; `refused` is the
        exception class it raises when the database does not let it in.
        """
        current = read_password(self.path)
        with self._lock:
            accepted, previous_in_use = self._accepted, self._previous_in_use
        if accepted is None or accepted == current:
            order = [current]
        elif previous_in_use:
            # Still mid-rotation: the old password is the likelier one, so the
            # database sees at most one refused attempt per process per step.
            order = [accepted, current]
        else:
            order = [current, accepted]
        failure = None
        for password in order:
            try:
                connection = open_connection(password)
            except refused as error:
                failure = error
                continue
            self._accepted_now(password, current)
            return connection
        raise failure

    def _accepted_now(self, password, current):
        previous = password != current
        with self._lock:
            before = self._accepted, self._previous_in_use
            self._accepted, self._previous_in_use = password, previous
        if before == (password, previous):
            return
        if previous:
            log.warning(
                "The database refused the password in the mounted file; still "
                "using the previous password. Finish the rotation by changing "
                "the role's password, or correct the Secret."
            )
        elif before[0] is not None:
            log.warning("The database accepted the password in the mounted file.")
