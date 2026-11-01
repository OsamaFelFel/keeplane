"""Spec 006 ST21 "Held-back requests": one Audit record per request held back.

ADR 025 and governance issue #29: personal-data detection can hold a request
back to the detection class. While the "Held-back requests" switch is on, each
held request gets one record with a reference, the time, the developer, the
project, the class it was handled as, why it was held, and the model it was
allowed to or refused for. It never holds the prompt, any other request text
or anything detection found.

One record per request, not per check: the gateway runs detection at its
route (entry) check and again at the selected-model check, which runs once
per backend attempt, retries included. Only the entry check records, because
it runs exactly once for each request and before any model is chosen, so it
also sees requests refused there. The selected-model check never records a
hold. Each gateway mode has one recording entry check: the managed installed
entry check, or the shared ``/internal/runtime/authorize`` check of a
customer-run gateway.

A failed write follows "Model answers": it is logged and the decision
stands. The record is written only after the decision has been made, so a
held request refused for a model that isn't approved for its class stays
refused, and an allowed one was already limited to approved models.
"""

import logging
import secrets

from accounts.models import User
from audit.services import DjangoAuditStore
from django.db import transaction
from personal_data.inspection import FAILED, FOUND, NOT_SENT, SLOW, UNAVAILABLE
from projects.models import Project

from .models import ModelApproval

KIND = "held_requests"

# Why the request was held: a category only, never what was found.
REASONS = {
    FOUND: "personal data detected",
    NOT_SENT: "request could not be read",
    UNAVAILABLE: "detector unavailable",
    SLOW: "check took too long",
    FAILED: "detector failed",
}
# Any other reason still records a hold, without guessing why.
UNKNOWN_REASON = "not checked"

logger = logging.getLogger(__name__)


def reference():
    """A random reference for this held request; derived from nothing in it."""
    return "HR-" + secrets.token_hex(6)


def description(ref, held_class, reason, project_name, model_id, allowed):
    why = REASONS.get(reason, UNKNOWN_REASON)
    model = f"model {model_id}" if model_id else "a model Keeplane doesn't know"
    outcome = (
        f"allowed to {model}, approved for it"
        if allowed
        else f"refused for {model}, not approved for it; nothing was sent"
    )
    return (
        f"Request {ref} held back as {held_class} ({why}); "
        f"project {project_name}; {outcome}"
    )


def record_held_request(hold, verdict, audit=None):
    """Record a held request if the switch is on; never raise.

    ``hold`` is the server's own decision: actor, project and model IDs, the
    detection class it was held to and whether it was allowed. ``verdict``
    carries only the reason category. Names come from Keeplane's own tables;
    a refused model ID is named only if Keeplane knows that model.
    """
    try:
        audit = audit or DjangoAuditStore()
        with transaction.atomic():
            if not audit.enabled(KIND):
                return False
            developer = User.objects.only("username").get(pk=hold["actor_id"])
            project = Project.objects.only("name").get(pk=hold["project_id"])
            model_id = hold["model_id"]
            if not hold["allowed"] and not ModelApproval.objects.filter(
                pk=model_id
            ).exists():
                model_id = None
            return audit.record_in_transaction(
                KIND,
                hold["actor_id"],
                developer.username,
                description(
                    reference(),
                    hold["held_class"],
                    getattr(verdict, "reason", None),
                    project.name,
                    model_id,
                    hold["allowed"],
                ),
            )
    except Exception as error:  # noqa: BLE001 - recording never changes the decision.
        # Only the error kind is logged: never credentials or request content.
        logger.warning(
            "Held-back request record was not written; the hold still applies (%s)",
            type(error).__name__,
        )
        return False
