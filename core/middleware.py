"""
Tenant context middleware for extracting and validating tenant information
"""
from django.utils.deprecation import MiddlewareMixin
from django.http import JsonResponse
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed
import hashlib
import threading


# Thread-local storage for tenant context
_thread_locals = threading.local()


def get_current_tenant():
    """Get the current tenant ID from thread-local storage"""
    return getattr(_thread_locals, 'tenant_id', None)


def set_current_tenant(tenant_id):
    """Set the current tenant ID in thread-local storage"""
    _thread_locals.tenant_id = tenant_id


def clear_current_tenant():
    """Clear the current tenant ID from thread-local storage"""
    if hasattr(_thread_locals, 'tenant_id'):
        delattr(_thread_locals, 'tenant_id')


class TenantContextMiddleware(MiddlewareMixin):
    """
    Middleware to extract tenant context from JWT token or API key
    and store it in thread-local storage for use by the Data Isolator
    """
    
    def process_request(self, request):
        """
        Extract tenant ID from authentication credentials and store in thread-local
        """
        # Clear any existing tenant context
        clear_current_tenant()
        
        # Skip tenant extraction for health check and public endpoints
        if self._is_public_endpoint(request.path):
            return None
        
        tenant_id = None
        
        # Try JWT authentication first
        if 'HTTP_AUTHORIZATION' in request.META:
            auth_header = request.META['HTTP_AUTHORIZATION']
            
            # Check for API key in Authorization header
            if auth_header.startswith('ApiKey '):
                api_key = auth_header.split(' ', 1)[1]
                tenant_id = self._extract_tenant_from_api_key(api_key)
            
            # Check for JWT Bearer token
            elif auth_header.startswith('Bearer '):
                tenant_id = self._extract_tenant_from_jwt(request)
        
        # Check for API key in X-API-Key header
        elif 'HTTP_X_API_KEY' in request.META:
            api_key = request.META['HTTP_X_API_KEY']
            tenant_id = self._extract_tenant_from_api_key(api_key)
        
        # Store tenant ID in thread-local storage
        if tenant_id:
            set_current_tenant(tenant_id)
            
            # Check if tenant is pending deletion
            if not self._is_tenant_active(tenant_id):
                return JsonResponse(
                    {
                        'error': {
                            'code': 'TENANT_PENDING_DELETION',
                            'message': 'This tenant is pending deletion and cannot make API requests'
                        }
                    },
                    status=403
                )
        
        return None
    
    def process_response(self, request, response):
        """Clear tenant context after request is processed"""
        clear_current_tenant()
        return response
    
    def process_exception(self, request, exception):
        """Clear tenant context if an exception occurs"""
        clear_current_tenant()
        return None
    
    def _is_public_endpoint(self, path):
        """Check if the endpoint is public and doesn't require tenant context"""
        public_paths = [
            '/health',
            '/api/docs',
            '/api/redoc',
            '/api/schema',
            '/api/tenants/register',  # Allow tenant registration
        ]
        return any(path.startswith(public_path) for public_path in public_paths)
    
    def _is_tenant_active(self, tenant_id):
        """Check if tenant is active (not pending deletion)"""
        try:
            # Lazy import to avoid circular dependency
            from tenants.services import TenantManager
            return TenantManager.check_pending_deletion_status(tenant_id)
        except Exception:
            return False
    
    def _extract_tenant_from_jwt(self, request):
        """Extract tenant ID from JWT token"""
        try:
            jwt_auth = JWTAuthentication()
            validated_token = jwt_auth.get_validated_token(
                jwt_auth.get_raw_token(jwt_auth.get_header(request))
            )
            return validated_token.get('tenant_id')
        except Exception:
            # If JWT validation fails, return None
            # The authentication backend will handle the error
            return None
    
    def _extract_tenant_from_api_key(self, api_key):
        """Extract tenant ID from API key"""
        try:
            # Lazy import to avoid circular dependency
            from authentication.models import APIKey
            
            # Hash the API key to match stored hash
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            
            # Look up API key in database
            api_key_obj = APIKey.objects.filter(
                key_hash=key_hash,
                revoked=False
            ).select_related('tenant').first()
            
            if api_key_obj:
                return api_key_obj.tenant_id
            
            return None
        except Exception:
            return None
