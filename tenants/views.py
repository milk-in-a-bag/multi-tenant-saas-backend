"""
Tenant management API views
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime

from .services import TenantManager
from .serializers import (
    TenantRegistrationSerializer,
    TenantDeletionSerializer,
    SubscriptionUpdateSerializer,
    TenantConfigSerializer,
    AuditLogQuerySerializer,
)
from core.audit_logger import AuditLogger
from core.middleware import get_current_tenant


@api_view(['POST'])
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
                identifier=serializer.validated_data['identifier'],
                admin_email=serializer.validated_data['admin_email'],
                admin_username=serializer.validated_data.get('admin_username')
            )
            return Response(result, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            return Response(
                {'error': e.detail}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['DELETE'])
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
        return Response(
            {'error': 'Tenant context required'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    serializer = TenantDeletionSerializer(data=request.data)
    if serializer.is_valid():
        try:
            TenantManager.delete_tenant(
                tenant_id=tenant_id,
                admin_user_id=request.user.id,
                password=serializer.validated_data['password']
            )
            return Response(
                {'message': 'Tenant marked for deletion. All data will be removed within 24 hours.'},
                status=status.HTTP_200_OK
            )
        except ValidationError as e:
            return Response(
                {'error': e.detail}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['PUT'])
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
        return Response(
            {'error': 'Tenant context required'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Check if user is admin
    if request.user.role != 'admin':
        return Response(
            {'error': 'Admin role required for subscription management'}, 
            status=status.HTTP_403_FORBIDDEN
        )
    
    serializer = SubscriptionUpdateSerializer(data=request.data)
    if serializer.is_valid():
        try:
            TenantManager.update_subscription(
                tenant_id=tenant_id,
                tier=serializer.validated_data['tier'],
                expiration_date=serializer.validated_data['expiration_date']
            )
            
            # Return updated config
            config = TenantManager.get_tenant_config(tenant_id)
            return Response(config, status=status.HTTP_200_OK)
            
        except ValidationError as e:
            return Response(
                {'error': e.detail}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_tenant_config(request):
    """
    Get current tenant configuration
    
    GET /api/tenants/config/
    """
    tenant_id = get_current_tenant()
    if not tenant_id:
        return Response(
            {'error': 'Tenant context required'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        config = TenantManager.get_tenant_config(tenant_id)
        serializer = TenantConfigSerializer(config)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response(
            {'error': e.detail}, 
            status=status.HTTP_400_BAD_REQUEST
        )


@api_view(['GET'])
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
        return Response(
            {'error': 'Tenant context required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    serializer = AuditLogQuerySerializer(data=request.query_params)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    result = AuditLogger.get_logs(
        tenant_id=tenant_id,
        start_date=data.get('start_date'),
        end_date=data.get('end_date'),
        page=data.get('page', 1),
        page_size=data.get('page_size', 50),
    )
    return Response(result, status=status.HTTP_200_OK)
