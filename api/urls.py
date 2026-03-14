"""
API URL routing
"""
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    # JWT authentication endpoints
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    
    # Custom authentication endpoints
    path('auth/', include('authentication.urls')),
    
    # Tenant management endpoints
    path('tenants/', include('tenants.urls')),

    # Widget endpoints (example business logic)
    path('widgets/', include('widgets.urls')),
]
