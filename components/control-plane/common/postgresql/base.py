"""Django's PostgreSQL backend, reading the password file for each connection.

Settings name the file in DATABASES["default"]["PASSWORD_FILE"]. See
common.database_password for the rotation behaviour. libpq already reads the
CA file named in OPTIONS["sslrootcert"] on every connection.
"""

import threading

from django.db.backends.postgresql import base

from common.database_password import DatabasePasswordUnavailable, RotatingPassword

_passwords = {}
_passwords_lock = threading.Lock()


def rotating_password(path):
    """One shared record per password file, for every connection in the process."""
    with _passwords_lock:
        return _passwords.setdefault(path, RotatingPassword(path))


class DatabaseWrapper(base.DatabaseWrapper):
    def get_new_connection(self, conn_params):
        path = self.settings_dict.get("PASSWORD_FILE")
        if not path:
            return super().get_new_connection(conn_params)
        parent = super().get_new_connection
        try:
            return rotating_password(path).connect(
                lambda password: parent({**conn_params, "password": password}),
                self.Database.OperationalError,
            )
        except DatabasePasswordUnavailable as error:
            raise self.Database.OperationalError(str(error)) from None
