"""
Widget API views - example tenant-isolated CRUD endpoints
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
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.middleware import get_current_tenant

from .serializers import (
    WidgetCreateSerializer,
    WidgetFilterSerializer,
    WidgetSerializer,
    WidgetUpdateSerializer,
)
from .services import WidgetService

# ---------------------------------------------------------------------------
# Shared schema helpers
# ---------------------------------------------------------------------------

_ErrorSerializer = inline_serializer(
    name="WidgetError",
    fields={
        "error": inline_serializer(
            name="WidgetErrorDetail",
            fields={
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "details": serializers.DictField(child=serializers.CharField()),
            },
        )
    },
)

_WidgetPageSerializer = inline_serializer(
    name="WidgetPage",
    fields={
        "count": serializers.IntegerField(),
        "page": serializers.IntegerField(),
        "page_size": serializers.IntegerField(),
        "results": WidgetSerializer(many=True),
    },
)

_RATE_LIMIT_NOTE = (
    "\n\n**Rate limiting:** Counts against the tenant hourly quota "
    "(100/1000/10000 req/hr for free/professional/enterprise). "
    "Returns 429 with Retry-After when exceeded."
)

_TENANT_ISOLATION_NOTE = (
    "\n\n**Tenant isolation:** Only widgets belonging to the authenticated tenant "
    "are visible or modifiable. Cross-tenant access is rejected."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _paginate(queryset, page, page_size):
    """Simple offset-based pagination helper."""
    total = queryset.count()
    offset = (page - 1) * page_size
    items = queryset[offset : offset + page_size]
    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "results": items,
    }


# ---------------------------------------------------------------------------
# widget_list — GET (list) + POST (create)
# ---------------------------------------------------------------------------


@extend_schema(
    tags=["widgets"],
    summary="List widgets",
    description=(
        "Return a paginated list of widgets for the authenticated tenant. "
        "Supports optional filtering by name substring and creation date range."
        + _TENANT_ISOLATION_NOTE
        + _RATE_LIMIT_NOTE
    ),
    parameters=[
        OpenApiParameter(
            "name_contains",
            str,
            OpenApiParameter.QUERY,
            description="Filter by name substring (case-insensitive)",
            required=False,
        ),
        OpenApiParameter(
            "created_after",
            str,
            OpenApiParameter.QUERY,
            description="Return widgets created after this datetime (ISO 8601)",
            required=False,
        ),
        OpenApiParameter(
            "created_before",
            str,
            OpenApiParameter.QUERY,
            description="Return widgets created before this datetime (ISO 8601)",
            required=False,
        ),
        OpenApiParameter("page", int, OpenApiParameter.QUERY, description="Page number (default: 1)", required=False),
        OpenApiParameter(
            "page_size",
            int,
            OpenApiParameter.QUERY,
            description="Results per page (default: 20, max: 100)",
            required=False,
        ),
    ],
    responses={
        200: OpenApiResponse(response=_WidgetPageSerializer, description="Paginated widget list"),
        400: OpenApiResponse(response=_ErrorSerializer, description="Invalid query parameters"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Not authenticated"),
        429: OpenApiResponse(description="Rate limit exceeded"),
    },
    methods=["GET"],
)
@extend_schema(
    tags=["widgets"],
    summary="Create widget",
    description=(
        "Create a new widget for the authenticated tenant. "
        "Widget names must be unique within a tenant. "
        "Requires admin or user role." + _TENANT_ISOLATION_NOTE + _RATE_LIMIT_NOTE
    ),
    request=WidgetCreateSerializer,
    responses={
        201: OpenApiResponse(response=WidgetSerializer, description="Widget created"),
        400: OpenApiResponse(response=_ErrorSerializer, description="Validation error or duplicate name"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Not authenticated"),
        403: OpenApiResponse(response=_ErrorSerializer, description="Admin or user role required"),
        429: OpenApiResponse(description="Rate limit exceeded"),
    },
    examples=[
        OpenApiExample(
            "Create widget request",
            value={"name": "My Widget", "description": "A sample widget", "metadata": {"color": "blue"}},
            request_only=True,
        ),
        OpenApiExample(
            "Widget created",
            value={
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "tenant_id": "acme-corp",
                "name": "My Widget",
                "description": "A sample widget",
                "metadata": {"color": "blue"},
                "created_by": "660e8400-e29b-41d4-a716-446655440001",
                "created_at": "2026-03-15T12:00:00Z",
                "updated_at": "2026-03-15T12:00:00Z",
            },
            response_only=True,
            status_codes=["201"],
        ),
    ],
    methods=["POST"],
)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def widget_list(request):
    """
    GET  /api/widgets/   - List widgets for the current tenant (all roles)
    POST /api/widgets/   - Create a new widget (admin and user roles)
    """
    tenant_id = get_current_tenant()
    if not tenant_id:
        return Response({"error": "Tenant context required"}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == "GET":
        filter_serializer = WidgetFilterSerializer(data=request.query_params)
        if not filter_serializer.is_valid():
            return Response(filter_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        params = filter_serializer.validated_data
        qs = WidgetService.list_widgets(
            tenant_id=tenant_id,
            name_contains=params.get("name_contains"),
            created_after=params.get("created_after"),
            created_before=params.get("created_before"),
        )
        page_data = _paginate(qs, params["page"], params["page_size"])
        page_data["results"] = WidgetSerializer(page_data["results"], many=True).data
        return Response(page_data, status=status.HTTP_200_OK)

    # POST - requires admin or user role
    if request.user.role not in ("admin", "user"):
        return Response(
            {"error": "Admin or user role required to create widgets"},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = WidgetCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    widget = WidgetService.create_widget(
        tenant_id=tenant_id,
        user_id=request.user.id,
        name=data["name"],
        description=data.get("description"),
        metadata=data.get("metadata", {}),
    )
    return Response(WidgetSerializer(widget).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# widget_detail — GET / PUT / PATCH / DELETE
# ---------------------------------------------------------------------------


@extend_schema(
    tags=["widgets"],
    summary="Get widget",
    description=(
        "Retrieve a single widget by ID. "
        "The widget must belong to the authenticated tenant." + _TENANT_ISOLATION_NOTE + _RATE_LIMIT_NOTE
    ),
    responses={
        200: OpenApiResponse(response=WidgetSerializer, description="Widget details"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Not authenticated"),
        404: OpenApiResponse(response=_ErrorSerializer, description="Widget not found"),
        429: OpenApiResponse(description="Rate limit exceeded"),
    },
    methods=["GET"],
)
@extend_schema(
    tags=["widgets"],
    summary="Update widget",
    description=(
        "Fully replace a widget. All writable fields must be supplied. "
        "Use PATCH for partial updates. Requires admin or user role." + _TENANT_ISOLATION_NOTE + _RATE_LIMIT_NOTE
    ),
    request=WidgetUpdateSerializer,
    responses={
        200: OpenApiResponse(response=WidgetSerializer, description="Updated widget"),
        400: OpenApiResponse(response=_ErrorSerializer, description="Validation error"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Not authenticated"),
        403: OpenApiResponse(response=_ErrorSerializer, description="Admin or user role required"),
        404: OpenApiResponse(response=_ErrorSerializer, description="Widget not found"),
        429: OpenApiResponse(description="Rate limit exceeded"),
    },
    methods=["PUT"],
)
@extend_schema(
    tags=["widgets"],
    summary="Partially update widget",
    description=(
        "Update one or more widget fields. Requires admin or user role." + _TENANT_ISOLATION_NOTE + _RATE_LIMIT_NOTE
    ),
    request=WidgetUpdateSerializer,
    responses={
        200: OpenApiResponse(response=WidgetSerializer, description="Updated widget"),
        400: OpenApiResponse(response=_ErrorSerializer, description="Validation error"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Not authenticated"),
        403: OpenApiResponse(response=_ErrorSerializer, description="Admin or user role required"),
        404: OpenApiResponse(response=_ErrorSerializer, description="Widget not found"),
        429: OpenApiResponse(description="Rate limit exceeded"),
    },
    methods=["PATCH"],
)
@extend_schema(
    tags=["widgets"],
    summary="Delete widget",
    description=(
        "Permanently delete a widget. Requires admin or user role." + _TENANT_ISOLATION_NOTE + _RATE_LIMIT_NOTE
    ),
    responses={
        204: OpenApiResponse(description="Widget deleted"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Not authenticated"),
        403: OpenApiResponse(response=_ErrorSerializer, description="Admin or user role required"),
        404: OpenApiResponse(response=_ErrorSerializer, description="Widget not found"),
        429: OpenApiResponse(description="Rate limit exceeded"),
    },
    methods=["DELETE"],
)
@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def widget_detail(request, widget_id):
    """
    GET    /api/widgets/<id>/  - Retrieve a widget (all roles)
    PUT    /api/widgets/<id>/  - Full update (admin and user roles)
    PATCH  /api/widgets/<id>/  - Partial update (admin and user roles)
    DELETE /api/widgets/<id>/  - Delete a widget (admin and user roles)
    """
    tenant_id = get_current_tenant()
    if not tenant_id:
        return Response({"error": "Tenant context required"}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == "GET":
        widget = WidgetService.get_widget(tenant_id, widget_id)
        return Response(WidgetSerializer(widget).data, status=status.HTTP_200_OK)

    # Mutating operations require admin or user role
    if request.user.role not in ("admin", "user"):
        return Response(
            {"error": "Admin or user role required for this operation"},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method in ("PUT", "PATCH"):
        serializer = WidgetUpdateSerializer(data=request.data, partial=(request.method == "PATCH"))
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        widget = WidgetService.update_widget(
            tenant_id=tenant_id,
            widget_id=widget_id,
            name=data.get("name"),
            description=data.get("description"),
            metadata=data.get("metadata"),
        )
        return Response(WidgetSerializer(widget).data, status=status.HTTP_200_OK)

    # DELETE
    WidgetService.delete_widget(tenant_id, widget_id)
    return Response(status=status.HTTP_204_NO_CONTENT)
