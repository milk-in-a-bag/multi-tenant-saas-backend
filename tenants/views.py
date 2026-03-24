"""
Tenant management API views
"""

from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core.audit_logger import AuditLogger
from core.middleware import get_current_tenant

from .serializers import (
    AuditLogQuerySerializer,
    SubscriptionUpdateSerializer,
    TenantConfigSerializer,
    TenantDeletionSerializer,
    TenantRegistrationSerializer,
)
from .services import TenantManager

# ---------------------------------------------------------------------------
# Inline response serializers for schema documentation
# ---------------------------------------------------------------------------

_ErrorSerializer = inline_serializer(
    name="TenantError",
    fields={
        "error": inline_serializer(
            name="TenantErrorDetail",
            fields={
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "details": serializers.DictField(child=serializers.CharField()),
            },
        )
    },
)

_TenantRegistrationResponseSerializer = inline_serializer(
    name="TenantRegistrationResponse",
    fields={
        "tenant_id": serializers.CharField(help_text="Unique tenant identifier"),
        "admin_username": serializers.CharField(help_text="Generated admin username"),
        "admin_password": serializers.CharField(help_text="Temporary admin password — change on first login"),
    },
)

_TenantDeletionResponseSerializer = inline_serializer(
    name="TenantDeletionResponse",
    fields={"message": serializers.CharField()},
)

_AuditLogEntrySerializer = inline_serializer(
    name="AuditLogEntry",
    fields={
        "id": serializers.UUIDField(),
        "tenant_id": serializers.CharField(),
        "event_type": serializers.CharField(),
        "user_id": serializers.UUIDField(allow_null=True),
        "timestamp": serializers.DateTimeField(),
        "details": serializers.DictField(),
        "ip_address": serializers.CharField(allow_null=True),
    },
)

_AuditLogPageSerializer = inline_serializer(
    name="AuditLogPage",
    fields={
        "count": serializers.IntegerField(),
        "page": serializers.IntegerField(),
        "page_size": serializers.IntegerField(),
        "results": serializers.ListField(child=_AuditLogEntrySerializer),
    },
)

_RATE_LIMIT_NOTE = (
    "\n\n**Rate limiting:** Counts against the tenant's hourly quota "
    "(100 / 1 000 / 10 000 req/hr for free / professional / enterprise). "
    "Returns `429` with `Retry-After` when exceeded."
)

_TENANT_ISOLATION_NOTE = (
    "\n\n**Tenant isolation:** All data is scoped to the tenant in the "
    "authentication credential. Cross-tenant access is rejected."
)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


@extend_schema(
    tags=["tenants"],
    summary="Register a new tenant",
    description=(
        "Create a new tenant and its initial admin user. "
        "Returns the tenant identifier and temporary admin credentials.\n\n"
        "No authentication is required — this is the entry point for new customers."
    ),
    request=TenantRegistrationSerializer,
    responses={
        201: OpenApiResponse(
            response=_TenantRegistrationResponseSerializer,
            description="Tenant created successfully",
        ),
        400: OpenApiResponse(response=_ErrorSerializer, description="Validation error or duplicate identifier"),
    },
    examples=[
        OpenApiExample(
            "Register request",
            value={"identifier": "acme-corp", "admin_email": "admin@acme.com"},
            request_only=True,
        ),
        OpenApiExample(
            "Register success",
            value={
                "tenant_id": "acme-corp",
                "admin_username": "admin",
                "admin_password": "Tmp$ecret42!",
            },
            response_only=True,
            status_codes=["201"],
        ),
    ],
    auth=[],
)
@api_view(["POST"])
@permission_classes([AllowAny])
def register_tenant(request):
    """
    Register a new tenant with admin user

    POST /api/tenants/register/
    {
        "identifier": "my-company",
        "admin_email": "admin@company.com",
        "admin_username": "admin"  // optional
    }
    """
    serializer = TenantRegistrationSerializer(data=request.data)
    if serializer.is_valid():
        try:
            result = TenantManager.register_tenant(
                identifier=serializer.validated_data["identifier"],
                admin_email=serializer.validated_data["admin_email"],
                admin_username=serializer.validated_data.get("admin_username"),
            )
            return Response(result, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response(
                {"error": {"code": "VALIDATION_ERROR", "message": str(e.detail), "details": {}}},
                status=status.HTTP_400_BAD_REQUEST,
            )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=["tenants"],
    summary="Delete current tenant (admin only)",
    description=(
        "Initiate tenant deletion. The admin must supply their password for "
        "re-authentication. The tenant is marked `pending_deletion` and all "
        "data is removed within 24 hours. All subsequent API requests for the "
        "tenant are rejected immediately." + _TENANT_ISOLATION_NOTE + _RATE_LIMIT_NOTE
    ),
    request=TenantDeletionSerializer,
    responses={
        200: OpenApiResponse(response=_TenantDeletionResponseSerializer, description="Tenant queued for deletion"),
        400: OpenApiResponse(response=_ErrorSerializer, description="Invalid password or request"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Not authenticated"),
        403: OpenApiResponse(response=_ErrorSerializer, description="Admin role required"),
        429: OpenApiResponse(description="Rate limit exceeded — see Retry-After header"),
    },
    examples=[
        OpenApiExample(
            "Delete request",
            value={"password": "my-admin-password"},
            request_only=True,
        ),
        OpenApiExample(
            "Delete queued",
            value={"message": "Tenant marked for deletion. All data will be removed within 24 hours."},
            response_only=True,
            status_codes=["200"],
        ),
    ],
)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_tenant(request):
    """
    Delete current tenant after password re-authentication

    DELETE /api/tenants/delete/
    {
        "password": "admin_password"
    }
    """
    tenant_id = get_current_tenant()
    if not tenant_id:
        return Response({"error": "Tenant context required"}, status=status.HTTP_400_BAD_REQUEST)

    serializer = TenantDeletionSerializer(data=request.data)
    if serializer.is_valid():
        try:
            TenantManager.delete_tenant(
                tenant_id=tenant_id, admin_user_id=request.user.id, password=serializer.validated_data["password"]
            )
            return Response(
                {"message": "Tenant marked for deletion. All data will be removed within 24 hours."},
                status=status.HTTP_200_OK,
            )
        except ValidationError as e:
            return Response(
                {"error": {"code": "VALIDATION_ERROR", "message": str(e.detail), "details": {}}},
                status=status.HTTP_400_BAD_REQUEST,
            )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=["tenants"],
    summary="Update subscription tier (admin only)",
    description=(
        "Change the subscription tier and expiration date for the current tenant. "
        "The new tier takes effect immediately and determines the hourly rate limit:\n"
        "- **free** → 100 req/hr\n"
        "- **professional** → 1 000 req/hr\n"
        "- **enterprise** → 10 000 req/hr\n\n"
        "When the subscription expires the tenant is automatically downgraded to free."
        + _TENANT_ISOLATION_NOTE
        + _RATE_LIMIT_NOTE
    ),
    request=SubscriptionUpdateSerializer,
    responses={
        200: OpenApiResponse(response=TenantConfigSerializer, description="Updated tenant configuration"),
        400: OpenApiResponse(response=_ErrorSerializer, description="Validation error"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Not authenticated"),
        403: OpenApiResponse(response=_ErrorSerializer, description="Admin role required"),
        429: OpenApiResponse(description="Rate limit exceeded — see Retry-After header"),
    },
    examples=[
        OpenApiExample(
            "Upgrade to professional",
            value={"tier": "professional", "expiration_date": "2027-01-01T00:00:00Z"},
            request_only=True,
        ),
    ],
)
@api_view(["PUT"])
@permission_classes([IsAuthenticated])
def update_subscription(request):
    """
    Update tenant subscription tier and expiration

    PUT /api/tenants/subscription/
    {
        "tier": "professional",
        "expiration_date": "2025-01-01T00:00:00Z"
    }
    """
    tenant_id = get_current_tenant()
    if not tenant_id:
        return Response({"error": "Tenant context required"}, status=status.HTTP_400_BAD_REQUEST)

    if request.user.role != "admin":
        return Response({"error": "Admin role required for subscription management"}, status=status.HTTP_403_FORBIDDEN)

    serializer = SubscriptionUpdateSerializer(data=request.data)
    if serializer.is_valid():
        try:
            TenantManager.update_subscription(
                tenant_id=tenant_id,
                tier=serializer.validated_data["tier"],
                expiration_date=serializer.validated_data["expiration_date"],
            )
            config = TenantManager.get_tenant_config(tenant_id)
            return Response(config, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response(
                {"error": {"code": "VALIDATION_ERROR", "message": str(e.detail), "details": {}}},
                status=status.HTTP_400_BAD_REQUEST,
            )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=["tenants"],
    summary="Get tenant configuration",
    description=(
        "Retrieve the current tenant's configuration including subscription tier, "
        "expiration date, rate limit, and status." + _TENANT_ISOLATION_NOTE + _RATE_LIMIT_NOTE
    ),
    responses={
        200: OpenApiResponse(response=TenantConfigSerializer, description="Tenant configuration"),
        400: OpenApiResponse(response=_ErrorSerializer, description="Tenant context missing"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Not authenticated"),
        429: OpenApiResponse(description="Rate limit exceeded — see Retry-After header"),
    },
    examples=[
        OpenApiExample(
            "Tenant config",
            value={
                "tenant_id": "acme-corp",
                "subscription_tier": "professional",
                "subscription_expiration": "2027-01-01T00:00:00Z",
                "rate_limit": 1000,
                "status": "active",
                "created_at": "2026-01-01T00:00:00Z",
            },
            response_only=True,
            status_codes=["200"],
        ),
    ],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_tenant_config(request):
    """
    Get current tenant configuration

    GET /api/tenants/config/
    """
    tenant_id = get_current_tenant()
    if not tenant_id:
        return Response({"error": "Tenant context required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        config = TenantManager.get_tenant_config(tenant_id)
        serializer = TenantConfigSerializer(config)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response(
            {"error": {"code": "VALIDATION_ERROR", "message": str(e.detail), "details": {}}},
            status=status.HTTP_400_BAD_REQUEST,
        )


@extend_schema(
    tags=["tenants"],
    summary="List audit logs",
    description=(
        "Retrieve paginated audit log entries for the current tenant. "
        "Logs include authentication events, role changes, API key operations, "
        "and subscription changes. Logs are retained for a minimum of 90 days.\n\n"
        "Results are always scoped to the authenticated tenant — no cross-tenant "
        "log access is possible." + _TENANT_ISOLATION_NOTE + _RATE_LIMIT_NOTE
    ),
    parameters=[
        OpenApiParameter(
            name="start_date",
            type=str,
            location=OpenApiParameter.QUERY,
            description="Filter logs from this datetime (ISO 8601)",
            required=False,
        ),
        OpenApiParameter(
            name="end_date",
            type=str,
            location=OpenApiParameter.QUERY,
            description="Filter logs up to this datetime (ISO 8601)",
            required=False,
        ),
        OpenApiParameter(
            name="page",
            type=int,
            location=OpenApiParameter.QUERY,
            description="Page number (default: 1)",
            required=False,
        ),
        OpenApiParameter(
            name="page_size",
            type=int,
            location=OpenApiParameter.QUERY,
            description="Results per page (default: 50, max: 200)",
            required=False,
        ),
    ],
    responses={
        200: OpenApiResponse(response=_AuditLogPageSerializer, description="Paginated audit log entries"),
        400: OpenApiResponse(response=_ErrorSerializer, description="Invalid query parameters"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Not authenticated"),
        429: OpenApiResponse(description="Rate limit exceeded — see Retry-After header"),
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_audit_logs(request):
    """
    Retrieve audit logs for the current tenant with optional date range filtering.

    GET /api/tenants/audit-logs/
    Query params:
        start_date: ISO 8601 datetime (optional)
        end_date:   ISO 8601 datetime (optional)
        page:       page number (default 1)
        page_size:  results per page (default 50, max 200)
    """
    tenant_id = get_current_tenant()
    if not tenant_id:
        return Response({"error": "Tenant context required"}, status=status.HTTP_400_BAD_REQUEST)

    serializer = AuditLogQuerySerializer(data=request.query_params)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    result = AuditLogger.get_logs(
        tenant_id=tenant_id,
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
        page=data.get("page", 1),
        page_size=data.get("page_size", 50),
    )
    return Response(result, status=status.HTTP_200_OK)
