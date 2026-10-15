"""Account transport, using the local account use cases during cutover."""

from urllib.parse import parse_qs

from django.middleware.csrf import get_token, rotate_token
from rest_framework.decorators import api_view
from rest_framework.response import Response


from common.api import (
    IDENTITY,
    PUBLIC_ORIGIN,
    failure,
    result,
    actor,
    admin,
    trusted_origin,
    action_error,
)


@api_view(["GET"])
def auth_options(request):
    response = Response({"sso_connected": False, "csrf_token": get_token(request)})
    response["Cache-Control"] = "no-store"
    return response


@api_view(["POST"])
def session(request):
    if not trusted_origin(request):
        return failure(403, "Sign in from Keeplane's page")
    if not isinstance(request.data, dict):
        return failure(400, "Enter a username and password")

    def sign_in():
        token = IDENTITY.login(
            request.data.get("username"), request.data.get("password")
        )
        rotate_token(request)
        response = Response({"signed_in": True})
        response.set_cookie(
            "keeplane_session",
            token,
            max_age=8 * 60 * 60,
            httponly=True,
            samesite="Strict",
            path="/",
            secure=PUBLIC_ORIGIN.startswith("https://"),
        )
        return response

    return result(sign_in)


@api_view(["GET"])
def identity(request):
    user = actor(request)
    return Response(user) if user else failure(401, "Sign in to Keeplane")


@api_view(["GET", "POST"])
def users(request):
    user, denied = admin(request)
    if denied:
        return denied
    if request.method == "GET":
        return result(
            lambda: Response(
                IDENTITY.users(parse_qs(request.META.get("QUERY_STRING", "")))
            )
        )
    denied = action_error(request)
    if denied:
        return denied
    return result(
        lambda: Response(IDENTITY.create_user(request.data, user["id"]), status=201)
    )


@api_view(["DELETE"])
def user_detail(request, user_id):
    _, denied = admin(request)
    if denied:
        return denied
    denied = action_error(request)
    if denied:
        return denied
    return result(lambda: Response(IDENTITY.delete_user(user_id)))


@api_view(["PUT"])
def user_role(request, user_id):
    _, denied = admin(request)
    if denied:
        return denied
    denied = action_error(request)
    if denied:
        return denied
    return result(
        lambda: Response(IDENTITY.change_role(user_id, request.data.get("role")))
    )


@api_view(["GET"])
def user_operation(request, operation_id):
    user, denied = admin(request)
    if denied:
        return denied
    return result(lambda: Response(IDENTITY.user_operation(operation_id, user["id"])))


@api_view(["GET", "PUT"])
def edition_note(request):
    user, denied = admin(request)
    if denied:
        return denied
    if request.method == "GET":
        return result(lambda: Response(IDENTITY.edition_note(user["id"])))
    denied = action_error(request)
    if denied:
        return denied
    return result(
        lambda: Response(
            IDENTITY.set_edition_note(user["id"], request.data.get("enabled"))
        )
    )


@api_view(["POST"])
def consume_edition_note(request):
    user, denied = admin(request)
    if denied:
        return denied
    denied = action_error(request)
    if denied:
        return denied
    return result(lambda: Response(IDENTITY.consume_edition_note(user["id"])))


@api_view(["POST"])
def sign_out(request):
    IDENTITY.logout(request.COOKIES.get("keeplane_session", ""))
    response = Response({"signed_out": True})
    response.delete_cookie("keeplane_session", path="/", samesite="Strict")
    response["Cache-Control"] = "no-store"
    return response
