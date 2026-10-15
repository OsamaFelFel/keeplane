"""Account transport, using the local account use cases during cutover."""

from rest_framework.decorators import api_view
from rest_framework.response import Response


from common.api import DATA_CLASSES, failure, settings_result, admin, action_error
from model_registry.use_cases import effective_model_ids


@api_view(["GET", "POST"])
def data_classes(request):
    user, denied = admin(request)
    if denied:
        return denied
    if request.method == "GET":

        def show():
            if not DATA_CLASSES.enabled():
                return Response({"enabled": False, "classes": []})
            status, body, effective = effective_model_ids()
            return Response(
                {"enabled": True, "classes": DATA_CLASSES.list(effective)}
                if status == 200
                else body,
                status=status,
            )

        return settings_result(show)
    denied = action_error(request)
    if denied:
        return denied
    if not isinstance(request.data, dict):
        return failure(400, "Enter a data class request")

    def add():
        effective = set()
        if request.data.get("approved_model_ids"):
            status, body, effective = effective_model_ids()
            if status != 200:
                return Response(body, status=status)
        return Response(
            DATA_CLASSES.add(request.data, effective, (user["id"], user["username"])),
            status=201,
        )

    return settings_result(add)


@api_view(["PUT"])
def data_class_mode(request):
    user, denied = admin(request)
    if denied:
        return denied
    denied = action_error(request)
    if denied:
        return denied
    if not isinstance(request.data, dict):
        return failure(400, "Enter a data class request")
    return settings_result(
        lambda: Response(
            DATA_CLASSES.set_enabled(
                request.data.get("enabled"), (user["id"], user["username"])
            )
        )
    )


@api_view(["PUT", "DELETE"])
def data_class_detail(request, class_id):
    user, denied = admin(request)
    if denied:
        return denied
    denied = action_error(request)
    if denied:
        return denied
    signed_actor = (user["id"], user["username"])
    if request.method == "DELETE":
        return settings_result(
            lambda: Response(DATA_CLASSES.remove(class_id, signed_actor))
        )
    if not isinstance(request.data, dict):
        return failure(400, "Enter a data class request")

    def edit():
        effective = set()
        if request.data.get("approved_model_ids"):
            status, body, effective = effective_model_ids()
            if status != 200:
                return Response(body, status=status)
        return Response(
            DATA_CLASSES.edit(class_id, request.data, effective, signed_actor)
        )

    return settings_result(edit)
