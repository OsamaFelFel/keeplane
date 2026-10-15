from django.apps import AppConfig
from django.db.backends.signals import connection_created


def configure_connection(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        # Match the account column's bytewise PostgreSQL collation locally.
        connection.connection.create_collation(
            "C", lambda left, right: (left > right) - (left < right)
        )


class CommonConfig(AppConfig):
    name = "common"

    def ready(self):
        connection_created.connect(
            configure_connection, dispatch_uid="keeplane-sqlite-collation"
        )
