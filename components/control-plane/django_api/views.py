"""Account transport, using the local account use cases during cutover."""

import os
import sqlite3
from urllib.parse import parse_qs

from django.http import HttpResponseRedirect
from rest_framework.decorators import api_view
from rest_framework.response import Response

from audit import AuditError, AuditStore
from data_classes import DataClassError, DataClassStore
from gateway_adapter import AgentgatewayModelAdapter
from local_identity import IdentityError, LocalIdentity
from model_catalog import ModelCatalog
from model_chat import ask_model
from model_listing import list_models
from model_management import ModelManagement
from model_removal import remove_model_setup
from runner_adapter import local_runner


AUDIT = AuditStore(os.environ["MODEL_APPROVAL_DB"])
IDENTITY = LocalIdentity(os.environ["ACCOUNT_DB"], os.environ["FIRST_ADMIN_PASSWORD_FILE"], AUDIT)
CATALOG = ModelCatalog(os.environ["MODEL_APPROVAL_DB"], AUDIT)
DATA_CLASSES = DataClassStore(os.environ["MODEL_APPROVAL_DB"], AUDIT)
MODEL_GATEWAY = AgentgatewayModelAdapter(
    os.environ.get("GATEWAY_URL", "http://gateway:4000"),
    os.environ.get("GATEWAY_RUNTIME_KEY_FILE", ""),
    os.environ.get("GATEWAY_ADMIN_KEY_FILE", ""))
RUNNER_URLS = {url.strip().rstrip("/") for url in
               os.environ.get("PREVIEW_RUNNER_URLS", "http://qwen:8080").split(",") if url.strip()}
PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN", "")
PUBLIC_ORIGIN_ALIASES = {part.strip() for part in
                         os.environ.get("PUBLIC_ORIGIN_ALIASES", "").split(",") if part.strip()}


def model_management(user):
    return ModelManagement(
        CATALOG, DATA_CLASSES, MODEL_GATEWAY, (user["id"], user["username"]),
        os.environ.get("GATEWAY_MODE", "managed"), os.environ.get("GATEWAY_FILE_CONFIG"),
        os.environ.get("PROVIDER_KEY_DIR", ""), RUNNER_URLS,
        {"openai": os.environ.get("PREVIEW_OPENAI_BASE_URL", ""),
         "anthropic": os.environ.get("PREVIEW_ANTHROPIC_BASE_URL", "")},
        os.environ.get("PREVIEW_PROVIDER_KEY", ""))


def failure(status, message):
    return Response({"error": message}, status=status)


def result(action):
    try:
        return action()
    except IdentityError as error:
        return failure(error.status, error.message)
    except sqlite3.Error:
        return failure(503, "Account storage is unavailable")


def settings_result(action):
    try:
        return action()
    except (DataClassError, AuditError) as error:
        return failure(error.status, error.message)
    except sqlite3.Error:
        return failure(503, "Keeplane settings storage is unavailable")


def effective_model_ids():
    status, listing = list_models(MODEL_GATEWAY.models, MODEL_GATEWAY.resources,
                                  CATALOG, os.environ.get("GATEWAY_FILE_CONFIG"), RUNNER_URLS)
    if status != 200:
        return status, listing, None
    return 200, {}, {item["id"] for item in listing["models"] if item.get("approved")}


def actor(request):
    token = request.COOKIES.get("keeplane_session", "")
    return IDENTITY.session(token)


def admin(request):
    user = actor(request)
    return user, None if user and user["role"] == "admin" else failure(
        403 if user else 401, "Admin access required" if user else "Sign in to Keeplane")


def trusted_origin(request):
    origin = request.headers.get("Origin")
    return not origin or origin in {PUBLIC_ORIGIN, *PUBLIC_ORIGIN_ALIASES}


def action_allowed(request):
    return (request.headers.get("X-Keeplane-Action") == "1" and
            request.content_type == "application/json" and trusted_origin(request))


def action_error(request):
    return None if action_allowed(request) else failure(403, "Changes require Keeplane's admin UI")


@api_view(["GET"])
def auth_options(request):
    return Response({"sso_connected": False})


@api_view(["POST"])
def session(request):
    if not trusted_origin(request):
        return failure(403, "Sign in from Keeplane's page")
    def sign_in():
        token = IDENTITY.login(request.data.get("username"), request.data.get("password"))
        response = Response({"signed_in": True})
        response.set_cookie("keeplane_session", token, max_age=8 * 60 * 60,
                            httponly=True, samesite="Strict", path="/",
                            secure=PUBLIC_ORIGIN.startswith("https://"))
        return response
    return result(sign_in)


@api_view(["GET"])
def identity(request):
    user = actor(request)
    return Response(user) if user else failure(401, "Sign in to Keeplane")


@api_view(["GET", "POST"])
def models(request):
    user, denied = admin(request)
    if denied:
        return denied
    if request.method == "POST":
        denied = action_error(request)
        if denied:
            return denied
        if not isinstance(request.data, dict):
            return failure(400, "Enter a model request")
        status, body = model_management(user).add(request.data)
        return Response(body, status=status)
    try:
        status, listing = list_models(MODEL_GATEWAY.models, MODEL_GATEWAY.resources,
                                      CATALOG, os.environ.get("GATEWAY_FILE_CONFIG"), RUNNER_URLS)
        return Response(listing, status=status)
    except sqlite3.Error:
        return failure(503, "Keeplane settings storage is unavailable")


@api_view(["POST", "DELETE"])
def model_setup(request, model_id):
    user, denied = admin(request)
    if denied:
        return denied
    denied = action_error(request)
    if denied:
        return denied
    if request.method == "POST":
        if not isinstance(request.data, dict):
            return failure(400, "Enter a model setup request")
        status, body = model_management(user).setup(model_id, request.data)
        return Response(body, status=status)
    try:
        status, result = remove_model_setup(
            model_id, (user["id"], user["username"]), CATALOG, MODEL_GATEWAY,
            os.environ.get("GATEWAY_FILE_CONFIG"), os.environ.get("PROVIDER_KEY_DIR", ""))
        return Response(result, status=status)
    except (IdentityError, AuditError) as error:
        return failure(error.status, error.message)
    except sqlite3.Error:
        return failure(503, "Keeplane settings storage is unavailable")


@api_view(["POST"])
def runner_models(request):
    _, denied = admin(request)
    if denied:
        return denied
    if not isinstance(request.data, dict):
        return failure(400, "Enter a runner address")
    status, body = local_runner(request.data.get("address"), RUNNER_URLS)
    return Response(body, status=status)


@api_view(["POST"])
def ask(request):
    _, denied = admin(request)
    if denied:
        return denied
    if not isinstance(request.data, dict):
        return failure(400, "Enter a model request")
    try:
        status, body = ask_model(request.data, CATALOG, MODEL_GATEWAY,
                                 os.environ.get("GATEWAY_FILE_CONFIG"))
        return Response(body, status=status)
    except sqlite3.Error:
        return failure(503, "Keeplane settings storage is unavailable")


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
            return Response({"enabled": True, "classes": DATA_CLASSES.list(effective)}
                            if status == 200 else body, status=status)
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
        return Response(DATA_CLASSES.add(request.data, effective,
                                         (user["id"], user["username"])), status=201)
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
    return settings_result(lambda: Response(DATA_CLASSES.set_enabled(
        request.data.get("enabled"), (user["id"], user["username"]))))


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
        return settings_result(lambda: Response(DATA_CLASSES.remove(class_id, signed_actor)))
    if not isinstance(request.data, dict):
        return failure(400, "Enter a data class request")
    def edit():
        effective = set()
        if request.data.get("approved_model_ids"):
            status, body, effective = effective_model_ids()
            if status != 200:
                return Response(body, status=status)
        return Response(DATA_CLASSES.edit(class_id, request.data, effective, signed_actor))
    return settings_result(edit)


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
    return settings_result(lambda: Response({"options": AUDIT.set_option(
        kind, request.data.get("enabled"))}))


@api_view(["GET"])
def audit_records(request):
    _, denied = admin(request)
    if denied:
        return denied
    try:
        page = int(request.query_params.get("page", "1"))
    except ValueError:
        return failure(400, "Page must be a number")
    return settings_result(lambda: Response(AUDIT.records(
        request.query_params.get("kind", "all"),
        request.query_params.get("search", ""), page)))


@api_view(["GET", "POST"])
def users(request):
    user, denied = admin(request)
    if denied:
        return denied
    if request.method == "GET":
        return result(lambda: Response(IDENTITY.users(parse_qs(request.META.get("QUERY_STRING", "")))))
    denied = action_error(request)
    if denied:
        return denied
    return result(lambda: Response(IDENTITY.create_user(request.data, user["id"]), status=201))


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
    return result(lambda: Response(IDENTITY.change_role(user_id, request.data.get("role"))))


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
    return result(lambda: Response(IDENTITY.set_edition_note(user["id"], request.data.get("enabled"))))


@api_view(["POST"])
def consume_edition_note(request):
    user, denied = admin(request)
    if denied:
        return denied
    denied = action_error(request)
    if denied:
        return denied
    return result(lambda: Response(IDENTITY.consume_edition_note(user["id"])))


@api_view(["GET"])
def sign_out(request):
    IDENTITY.logout(request.COOKIES.get("keeplane_session", ""))
    response = HttpResponseRedirect("/sign-in")
    response.delete_cookie("keeplane_session", path="/", samesite="Strict")
    response["Cache-Control"] = "no-store"
    return response
