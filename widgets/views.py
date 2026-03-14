"""
Widget API views - example tenant-isolated CRUD endpoints
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .services import WidgetService
from .serializers import (
    WidgetCreateSerializer,
    WidgetUpdateSerializer,
    WidgetSerializer,
    WidgetFilterSerializer,
)
from authentication.permissions import IsAdminOrUser
from core.middleware import get_current_tenant


def _paginate(queryset, page, page_size):
    """Simple offset-based pagination helper."""
    total = queryset.count()
    offset = (page - 1) * page_size
    items = queryset[offset: offset + page_size]
    return {
        'count': total,
        'page': page,
        'page_size': page_size,
        'results': items,
    }


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def widget_list(request):
    """
    GET  /api/widgets/        - List widgets for the current tenant (all roles)
    POST /api/widgets/        - Create a new widget (admin and user roles)
    """
    tenant_id = get_current_tenant()
    if not tenant_id:
        return Response({'error': 'Tenant context required'}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        filter_serializer = WidgetFilterSerializer(data=request.query_params)
        if not filter_serializer.is_valid():
            return Response(filter_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        params = filter_serializer.validated_data
        qs = WidgetService.list_widgets(
            tenant_id=tenant_id,
            name_contains=params.get('name_contains'),
            created_after=params.get('created_after'),
            created_before=params.get('created_before'),
        )
        page_data = _paginate(qs, params['page'], params['page_size'])
        page_data['results'] = WidgetSerializer(page_data['results'], many=True).data
        return Response(page_data, status=status.HTTP_200_OK)

    # POST - requires admin or user role
    if request.user.role not in ('admin', 'user'):
        return Response(
            {'error': 'Admin or user role required to create widgets'},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = WidgetCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    widget = WidgetService.create_widget(
        tenant_id=tenant_id,
        user_id=request.user.id,
        name=data['name'],
        description=data.get('description'),
        metadata=data.get('metadata', {}),
    )
    return Response(WidgetSerializer(widget).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
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
        return Response({'error': 'Tenant context required'}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        widget = WidgetService.get_widget(tenant_id, widget_id)
        return Response(WidgetSerializer(widget).data, status=status.HTTP_200_OK)

    # Mutating operations require admin or user role
    if request.user.role not in ('admin', 'user'):
        return Response(
            {'error': 'Admin or user role required for this operation'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method in ('PUT', 'PATCH'):
        serializer = WidgetUpdateSerializer(data=request.data, partial=(request.method == 'PATCH'))
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        widget = WidgetService.update_widget(
            tenant_id=tenant_id,
            widget_id=widget_id,
            name=data.get('name'),
            description=data.get('description'),
            metadata=data.get('metadata'),
        )
        return Response(WidgetSerializer(widget).data, status=status.HTTP_200_OK)

    # DELETE
    WidgetService.delete_widget(tenant_id, widget_id)
    return Response(status=status.HTTP_204_NO_CONTENT)
