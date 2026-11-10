"""Spec 006 ST21 "Held-back requests": one Audit record per request held back.

ADR 025 and governance issue #29: personal-data detection can hold a request
back to the detection class. While the "Held-back requests" switch is on, each
held request gets one record with a reference, the time, the developer, the
project, the class it was handled as, why it was held, and the model it was
allowed to or refused for. It never holds the prompt, any other request text
or anything detection found. Following the Audit design's row, it reads
"Request [Reference] in [Project] held back by detection, handled as [Class]
(Personal data detected); approved model [Model]" when personal data was
found, and "Request [Reference] in [Project] held back because detection
couldn't check it, handled as [Class] ([Why]); approved model [Model]" for
every other reason. Either form ends "model [Model] isn't approved for it,
nothing was sent" when the model isn't approved for the class. Records stored
before keep their text and are never rewritten.

Every held request is recorded; duplicates are kept down. The gateway runs
detection at its route (entry) check, once per request, and again at the
selected-model check, once per backend attempt, retries included. The entry
check records every hold. The selected-model check records a hold only for
the reasons that can differ between the two checks (detection down, too slow
or failed, see ``FINAL_CHECK_REASONS``): personal data, unreadable text and a
request too long to check give the same answer at both checks, so the entry
check has already recorded those. A request held at the final check for an outage reason may therefore
have a second record, from the entry check or a retry; nothing derived from
the request is stored to tell them apart (owner decision on PR #204: a rare
duplicate is acceptable, a missing record isn't). Each gateway mode has one
recording pair: the managed installed checks, or the shared
``/internal/runtime/authorize`` checks of a customer-run gateway.

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
from personal_data.inspection import (
    FAILED,
    FOUND,
    LIMIT_SECONDS,
    NOT_SENT,
    SLOW,
    TOO_LONG,
    UNAVAILABLE,
)
from projects.models import Project

from .models import ModelApproval

KIND = "held_requests"

# Why the request was held: a category only, never what was found.
REASONS = {
    FOUND: "Personal data detected",
    NOT_SENT: "Request couldn't be read",
    UNAVAILABLE: "Detection was down",
    SLOW: f"Detection took longer than {round(LIMIT_SECONDS * 1000)} ms",
    FAILED: "Detection failed",
    # A request too long to check within the limit (owner decision on #203:
    # very large requests are held); recorded as a slow check.
    TOO_LONG: f"Detection took longer than {round(LIMIT_SECONDS * 1000)} ms",
}
# Any other reason still records a hold: detection gave no clean answer.
UNKNOWN_REASON = REASONS[FAILED]
# Reasons the final check may meet even when the entry check did not hold.
# A request too long to check is held at both checks alike, so, like personal
# data, only the entry check records it.
FINAL_CHECK_REASONS = frozenset({UNAVAILABLE, SLOW, FAILED})

logger = logging.getLogger(__name__)


def reference():
    """A random reference for this held request; derived from nothing in it."""
    return "HR-" + secrets.token_hex(6)


def description(ref, held_class, reason, project_name, model_id, allowed):
    why = REASONS.get(reason, UNKNOWN_REASON)
    # "Approved", not "sent": a later key check can still refuse the request.
    model = f"model {model_id}" if model_id else "a model Keeplane doesn't know"
    outcome = (
        f"approved {model}"
        if allowed
        else f"{model} isn't approved for it, nothing was sent"
    )
    # The approved Audit design's row, "Request held back by detection,
    # handled as [Class]", with the details ST21 and D178 require. A hold
    # without a finding says detection couldn't check the request.
    how = "by detection" if reason == FOUND else "because detection couldn't check it"
    return (
        f"Request {ref} in {project_name} held back {how}, "
        f"handled as {held_class} ({why}); {outcome}"
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
