"""Read the migration ledger without changing the database."""

from functools import cache

from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder


@cache
def known_migrations():
    loader = MigrationLoader(None)
    return frozenset(loader.disk_migrations), {
        name: tuple(migration.replaces)
        for name, migration in loader.replacements.items()
    }


def schema_ready(connection):
    required, replacements = known_migrations()
    applied = set(
        MigrationRecorder.Migration.objects.using(connection.alias).values_list(
            "app", "name"
        )
    )
    # Django accepts either a squash or all of the migrations it replaces.
    for replacement, originals in replacements.items():
        if replacement in applied:
            applied.update(originals)
        elif all(original in applied for original in originals):
            applied.add(replacement)
    return required.issubset(applied)
