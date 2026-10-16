from django.urls import path
from . import oauth_device, oauth_views, views

urlpatterns = [
    path("oauth/authorize/", oauth_views.authorize),
    path("oauth/token/", oauth_views.token),
    path("oauth/device/", oauth_device.start),
    path("oauth/confirm-device/", oauth_device.confirm),
    path("api/auth-options", views.auth_options),
    path("api/session", views.session),
    path("api/identity", views.identity),
    path("api/users", views.users),
    path("api/users/<str:user_id>", views.user_detail),
    path("api/users/<str:user_id>/role", views.user_role),
    path("api/user-operations/<str:operation_id>", views.user_operation),
    path("api/edition-note", views.edition_note),
    path("api/edition-note/consume", views.consume_edition_note),
    path("sign-out", views.sign_out),
]
