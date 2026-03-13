"""
Authentication API views
"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from .services import AuthService
from .serializers import LoginSerializer


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