"""Spec 006 ST21 "Model answers": one Audit record per request sent to a model.

Owner decision (governance issue #36): a record is written each time the final
selected-model check lets a developer's request through to a model. It names
the time, the developer, the project and the model, and nothing else: no
prompt or answer text, no session, gateway or provider key. A failed write
never blocks the developer; it is logged and the request stays allowed.
"""

import logging

from accounts.models import User
from audit.services import DjangoAuditStore
from django.db import transaction
from projects.models import Project

KIND = "model_answers"

logger = logging.getLogger(__name__)


def description(model_id, project_name):
    return f"Request sent to model {model_id}; project {project_name}"


def record_sent_request(decision, audit=None):
    """Record an allowed decision if the switch is on; never raise.

    `decision` is the canonical result of the authorization step: the server's
    actor, project and model IDs. Names are read from Keeplane's own records,
    never from the request.
    """
    try:
        audit = audit or DjangoAuditStore()
        with transaction.atomic():
            if not audit.enabled(KIND):
                return False
            developer = User.objects.only("username").get(pk=decision["actor_id"])
            project = Project.objects.only("name").get(pk=decision["project_id"])
            return audit.record_in_transaction(
                KIND,
                decision["actor_id"],
                developer.username,
                description(decision["model_id"], project.name),
            )
    except Exception as error:  # noqa: BLE001 - recording must not refuse work.
        # Only the error kind is logged: never credentials or request content.
        logger.warning(
            "Model answers record was not written; the request was allowed (%s)",
            type(error).__name__,
        )
        return False
