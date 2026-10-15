"""Account transport, using the local account use cases during cutover."""

from rest_framework.decorators import api_view
from rest_framework.response import Response


from common.api import AUDIT, failure, settings_result, admin, action_error


@api_view(["GET"])
def audit_options(request):
    _, denied = admin(request)
    if denied:
        return denied
    return settings_result(lambda: Response({"options": AUDIT.options()}))


@api_view(["PUT"])
def audit_option(request, kind):
    _, denied = admin(request)
    if denied:
        return denied
    denied = action_error(request)
    if denied:
        return denied
    if not isinstance(request.data, dict):
        return failure(400, "Enter an Audit option request")
    return settings_result(
        lambda: Response(
            {"options": AUDIT.set_option(kind, request.data.get("enabled"))}
        )
    )


@api_view(["GET"])
def audit_records(request):
    _, denied = admin(request)
    if denied:
        return denied
    try:
        page = int(request.query_params.get("page", "1"))
    except ValueError:
        return failure(400, "Page must be a number")
    return settings_result(
        lambda: Response(
            AUDIT.records(
                request.query_params.get("kind", "all"),
                request.query_params.get("search", ""),
                page,
            )
        )
    )
