"""
Custom authentication backends for DRF
"""
# EXTENSION_POINT: authentication-providers
# Add custom authentication backends by subclassing BaseAuthentication.
# Implement authenticate(self, request) to support new credential types
# (e.g., OAuth2, SAML, LDAP, magic links).
# Register your backend in settings.py under REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES'].
# See: docs/extension-points/authentication-providers.md
import hashlib
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed


class APIKeyAuthentication(BaseAuthentication):
    """
    DRF authentication backend for API key authentication.

    Accepts API keys via:
    - Authorization: ApiKey <key> header
    - X-API-Key: <key> header
    """

    def authenticate(self, request):
        api_key = self._get_api_key(request)

        if api_key is None:
            # No API key header present — let other authenticators try
            return None

        return self._authenticate_key(api_key)

    def _get_api_key(self, request):
        """Extract raw API key from request headers."""
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('ApiKey '):
            return auth_header.split(' ', 1)[1].strip()

        x_api_key = request.META.get('HTTP_X_API_KEY', '')
        if x_api_key:
            return x_api_key.strip()

        return None

    def _authenticate_key(self, raw_key):
        """Validate the API key and return (user, None) or raise AuthenticationFailed."""
        from authentication.models import APIKey

        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        try:
            api_key_obj = (
                APIKey.objects
                .filter(key_hash=key_hash, revoked=False)
                .select_related('user')
                .get()
            )
        except APIKey.DoesNotExist:
            raise AuthenticationFailed('Invalid or revoked API key.')

        return (api_key_obj.user, None)
