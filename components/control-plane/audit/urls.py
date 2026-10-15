from django.urls import path
from . import views

urlpatterns = [
    path("api/audit/options", views.audit_options),
    path("api/audit/options/<str:kind>", views.audit_option),
    path("api/audit/records", views.audit_records),
]
