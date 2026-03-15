"""
Health check endpoint for monitoring system status.
No authentication required.
"""
from datetime import datetime, timezone

from django.db import connection
from django.db.utils import OperationalError
from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


_HealthResponseSerializer = inline_serializer(
    name='HealthResponse',
    fields={
        'status': serializers.ChoiceField(choices=['healthy', 'unhealthy']),
        'database': serializers.ChoiceField(choices=['healthy', 'unhealthy']),
        'timestamp': serializers.DateTimeField(),
    },
)


@extend_schema(
    tags=['system'],
    summary='Health check',
    description=(
        'Returns the overall system health and individual component statuses. '
        'No authentication is required. Responds within 100 ms.'
    ),
    responses={
        200: OpenApiResponse(response=_HealthResponseSerializer, description='System is healthy'),
        503: OpenApiResponse(response=_HealthResponseSerializer, description='One or more components are unhealthy'),
    },
    auth=[],
)
@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def health_check(request):
    """
    Returns system health status including database connectivity.
    Responds with HTTP 200 when healthy, HTTP 503 when unhealthy.
    """
    db_status = "healthy"

    try:
        connection.ensure_connection()
    except OperationalError:
        db_status = "unhealthy"

    overall_status = "healthy" if db_status == "healthy" else "unhealthy"
    http_status = 200 if overall_status == "healthy" else 503

    return Response(
        {
            "status": overall_status,
            "database": db_status,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        },
        status=http_status,
    )
