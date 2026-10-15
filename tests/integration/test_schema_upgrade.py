"""The app split preserves an already migrated database and its records."""

import pytest
from tests.fixtures.migration_probe import check_upgrade


@pytest.mark.django_db(transaction=True)
def test_existing_django_schema_upgrade():
    assert check_upgrade() == {
        "previous_schema_upgraded": True,
        "record_types_preserved": 12,
    }
