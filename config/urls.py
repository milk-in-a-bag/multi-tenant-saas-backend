"""
URL configuration for multi-tenant SaaS project.
"""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from api.health import health_check

urlpatterns = [
    # Redirect root to Swagger UI
    path("", RedirectView.as_view(url="/api/docs/", permanent=False)),
    # Health check - no authentication required
    path("health", health_check, name="health_check"),
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    # OpenAPI specification (JSON) — Requirements 19.1, 19.5
    path("api/docs/openapi.json", SpectacularAPIView.as_view(), name="schema"),
    # Interactive Swagger UI — Requirements 19.5
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    # ReDoc alternative documentation — Requirements 19.5
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
