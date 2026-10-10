from django.urls import path

from . import views

urlpatterns = [
    path("api/auth-options", views.auth_options),
    path("api/session", views.session),
    path("api/identity", views.identity),
    path("api/models", views.models),
    path("api/users", views.users),
    path("api/users/<str:user_id>", views.user_detail),
    path("api/users/<str:user_id>/role", views.user_role),
    path("api/user-operations/<str:operation_id>", views.user_operation),
    path("api/edition-note", views.edition_note),
    path("api/edition-note/consume", views.consume_edition_note),
    path("sign-out", views.sign_out),
]
