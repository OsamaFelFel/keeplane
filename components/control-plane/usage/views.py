"""The developer's own usage: report after a turn, read today and this month.

Both routes take the account from the CLI's bearer sign-in only. There is no
parameter for another account and no admin route (D191, ADR 029).
"""

import uuid

from accounts.authentication import RuntimeSessionAuthentication, runtime_bearer_only
from common.errors import StorageUnavailable
from django.db import DatabaseError, transaction
from django.views.decorators.cache import never_cache
from model_registry import runtime_views
from model_registry.policy import ModelPolicyUnavailable
from projects.access import organization_project_access
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import totals

STORAGE = (DatabaseError, StorageUnavailable)


def storage_unavailable():
    return Response({"error": "Usage storage is unavailable"}, status=503)


def record(request):
    body = request.data
    if not isinstance(body, dict):
        return Response({"error": "Send one usage report"}, status=400)
    # Any other field, such as an account ID, a prompt or a path, is ignored.
    try:
        project_id = str(uuid.UUID(str(body.get("project_id"))))
    except (ValueError, TypeError, AttributeError):
        return Response({"error": "This project is unavailable"}, status=403)
    model_id = body.get("model")
    if not isinstance(model_id, str) or not 0 < len(model_id) <= 256:
        return Response({"error": "Send the model's ID"}, status=400)
    try:
        counts = totals.capped(body)
    except totals.UsageError as error:
        return Response({"error": error.message}, status=400)
    try:
        allowed = organization_project_access(str(request.user.pk), project_id)
    except STORAGE:
        return storage_unavailable()
    if not allowed:
        return Response({"error": "This project is unavailable"}, status=403)
    try:
        eligible = runtime_views.model_policy().eligible_model_ids(project_id)
    except (ModelPolicyUnavailable, StorageUnavailable):
        return Response({"error": "Model policy is unavailable"}, status=503)
    if model_id not in eligible:
        return Response(
            {"error": "This model is not eligible for the project"}, status=403
        )
    try:
        totals.add(request.user.pk, model_id, counts)
    except STORAGE:
        return storage_unavailable()
    return Response(status=204)


def read(request):
    if set(request.query_params) - {"tz"}:
        return Response({"error": "Send only a time zone"}, status=400)
    try:
        zone = totals.time_zone(request.query_params.get("tz"))
    except totals.UsageError as error:
        return Response({"error": error.message}, status=400)
    try:
        with transaction.atomic():
            totals.delete_old_totals()
            usage = totals.own_usage(request.user.pk, zone)
    except STORAGE:
        return storage_unavailable()
    return Response(usage)


@never_cache
@runtime_bearer_only
@api_view(["GET", "POST"])
@authentication_classes([RuntimeSessionAuthentication])
@permission_classes([IsAuthenticated])
def usage(request):
    if request.method == "POST":
        return record(request)
    return read(request)
