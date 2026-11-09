from django.urls import path

from . import views

urlpatterns = [path("api/runtime/usage", views.usage)]
