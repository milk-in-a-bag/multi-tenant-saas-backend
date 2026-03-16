"""
URL patterns for authentication API
"""

from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login, name="auth-login"),
    path("api-keys/", views.generate_api_key, name="generate-api-key"),
    path("api-keys/<str:key_id>/", views.revoke_api_key, name="revoke-api-key"),
]
