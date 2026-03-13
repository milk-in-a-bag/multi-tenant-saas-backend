"""
Authentication API views
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from .services import AuthService
from .serializers import LoginSerializer
from .permissions import RoleBasedPermission, IsAdmin


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """
    Authenticate user and return JWT tokens
    
    POST /api/auth/login/
    {
        "tenant_id": "my-company",
        "username": "admin@company.com",
        "password": "password123"
    }
    """
    serializer = LoginSerializer(data=request.data)
    if serializer.is_valid():
        try:
            # Get client IP address
            ip_address = request.META.get('REMOTE_ADDR')
            
            result = AuthService.authenticate_user(
                tenant_id=serializer.validated_data['tenant_id'],
                username=serializer.validated_data['username'],
                password=serializer.validated_data['password'],
                ip_address=ip_address
            )
            return Response(result, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response(
                {'error': e.detail}, 
                status=status.HTTP_401_UNAUTHORIZED
            )
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdmin])
def generate_api_key(request):
    """
    Generate API key for a user (admin only)
    
    POST /api/auth/api-keys/
    {
        "user_id": "uuid-of-user"
    }
    """
    user_id = request.data.get('user_id')
    
    if not user_id:
        return Response(
            {'error': 'user_id is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        result = AuthService.generate_api_key(
            tenant_id=request.user.tenant_id,
            user_id=user_id,
            requesting_user_id=str(request.user.id)
        )
        return Response(result, status=status.HTTP_201_CREATED)
    except ValidationError as e:
        return Response(
            {'error': e.detail},
            status=status.HTTP_400_BAD_REQUEST
        )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated, IsAdmin])
def revoke_api_key(request, key_id):
    """
    Revoke an API key (admin only)
    
    DELETE /api/auth/api-keys/{key_id}/
    """
    try:
        AuthService.revoke_api_key(
            tenant_id=request.user.tenant_id,
            key_id=key_id,
            requesting_user_id=str(request.user.id)
        )
        return Response(
            {'message': 'API key revoked successfully'},
            status=status.HTTP_200_OK
        )
    except ValidationError as e:
        return Response(
            {'error': e.detail},
            status=status.HTTP_400_BAD_REQUEST
        )
