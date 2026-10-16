"""Real installer + actual OAuth issuer, confined to the trusted server container."""

import json
import uuid
from pathlib import Path
from threading import Event

from tests.fixtures.installed_cli_provider import InstalledCliProvider
from tests.fixtures.installed_runtime import bootstrap

if __name__ == "__main__":
    seed = bootstrap(InstalledCliProvider)
    from data_classes.models import ProjectClass
    from django.core.management import call_command
    from projects.services import DjangoProjectStore

    call_command("register_cli_client", verbosity=0)
    alternate = str(uuid.uuid4())
    DjangoProjectStore().register_use(
        seed["accounts"]["a"]["id"], alternate, "Other allowed project"
    )
    ProjectClass.objects.create(project_id=alternate, data_class_id="confidential")
    seed["alternate_project_id"] = alternate
    ready = Path("/state/ready.json")
    ready.write_text(json.dumps(seed))
    ready.chmod(0o600)
    Event().wait()
