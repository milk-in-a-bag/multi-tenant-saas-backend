"""
Authentication service for handling JWT tokens and API keys
"""

import hashlib
import secrets
from datetime import datetime
from datetime import timezone as dt_timezone

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from core.audit_logger import AuditLogger
from core.middleware import clear_current_tenant, set_current_tenant

from .models import APIKey, User


class AuthService:
    """
    Service class for authentication operations including
    JWT token generation and API key management
    """

    # EXTENSION_POINT: authorization-rules
    # Customize role-to-operation mappings by modifying OPERATION_PERMISSIONS or
    # replacing this dict with a dynamic lookup (e.g., database-driven permissions).
    # Add new roles (e.g., 'billing', 'support') or new operations (e.g., 'export')
    # by extending this mapping and updating authorize_operation() accordingly.
    # See: docs/extension-points/authorization-rules.md

    # Operation-to-role mapping
    OPERATION_PERMISSIONS = {
        "admin": ["read", "write", "delete", "admin"],
        "user": ["read", "write"],
        "read_only": ["read"],
    }

    @staticmethod
    def authorize_operation(role, operation):
        """
        Check if a role has permission to perform an operation

        Args:
            role: User role ('admin', 'user', or 'read_only')
            operation: Operation to check ('read', 'write', 'delete', or 'admin')

        Returns:
            bool: True if role permits operation, False otherwise
        """
        if role not in AuthService.OPERATION_PERMISSIONS:
            # Invalid role defaults to most restrictive (no permissions)
            return False

        allowed_operations = AuthService.OPERATION_PERMISSIONS[role]
        return operation in allowed_operations

    @staticmethod
    def authenticate_user(tenant_id, username, password, ip_address=None):
        """
        Authenticate user with credentials and generate JWT token

        Args:
            tenant_id: Tenant identifier
            username: Username or email
            password: User password
            ip_address: Client IP address for audit logging

        Returns:
            dict: {
                'access_token': str,
                'refresh_token': str,
                'user_id': str,
                'tenant_id': str,
                'role': str
            }

        Raises:
            ValidationError: If credentials are invalid
        """
        try:
            # Set tenant context for user lookup
            set_current_tenant(tenant_id)

            # Try to find user by username or email
            try:
                if "@" in username:
                    user = User.objects.get(email=username, tenant_id=tenant_id)
                else:
                    user = User.objects.get(username=username, tenant_id=tenant_id)
            except User.DoesNotExist:
                AuditLogger.log_authentication_failure(
                    tenant_id=tenant_id,
                    username=username,
                    ip_address=ip_address,
                )
                raise ValidationError({"error": "Invalid credentials"})

            # Check password
            if not user.check_password(password):
                AuditLogger.log_authentication_failure(
                    tenant_id=tenant_id,
                    username=username,
                    user_id=user.id,
                    ip_address=ip_address,
                )
                raise ValidationError({"error": "Invalid credentials"})

            # Check if user is active
            if not user.is_active:
                raise ValidationError({"error": "User account is disabled"})

            # Generate JWT tokens with custom claims
            refresh = RefreshToken.for_user(user)
            refresh["tenant_id"] = tenant_id
            refresh["role"] = user.role

            # Log successful authentication
            AuditLogger.log_authentication_success(
                tenant_id=tenant_id,
                user_id=user.id,
                username=username,
                ip_address=ip_address,
            )

            return {
                "access_token": str(refresh.access_token),
                "refresh_token": str(refresh),
                "user_id": str(user.id),
                "tenant_id": tenant_id,
                "role": user.role,
            }

        finally:
            clear_current_tenant()

    @staticmethod
    def validate_token(token):
        """
        Validate JWT token and extract user context

        Args:
            token: JWT token string

        Returns:
            dict: {
                'valid': bool,
                'user_id': str,
                'tenant_id': str,
                'role': str,
                'expires_at': datetime
            } or {
                'valid': False,
                'error': str
            }
        """
        try:
            # Decode and verify the token
            access_token = AccessToken(token)

            # Extract claims - user_id is stored as 'user_id' in the token payload
            # The RefreshToken.for_user() method automatically adds user_id
            user_id = access_token.payload.get("user_id")
            tenant_id = access_token.payload.get("tenant_id")
            role = access_token.payload.get("role")
            exp = access_token.payload.get("exp")

            # Convert expiration timestamp to datetime
            expires_at = datetime.fromtimestamp(exp, tz=dt_timezone.utc) if exp else None

            return {
                "valid": True,
                "user_id": str(user_id),
                "tenant_id": tenant_id,
                "role": role,
                "expires_at": expires_at,
            }

        except (TokenError, InvalidToken) as e:
            return {"valid": False, "error": str(e)}
        except Exception as e:
            return {"valid": False, "error": f"Invalid token: {str(e)}"}

    @staticmethod
    def generate_api_key(tenant_id, user_id, requesting_user_id):
        """
        Generate a new API key for a user

        Args:
            tenant_id: Tenant identifier
            user_id: User to create API key for
            requesting_user_id: User requesting the API key creation

        Returns:
            dict: {
                'key_id': str,
                'api_key': str,  # Only returned once
                'created_at': datetime
            }

        Raises:
            ValidationError: If user not found or insufficient permissions
        """
        try:
            set_current_tenant(tenant_id)

            # Verify requesting user is admin
            try:
                User.objects.get(id=requesting_user_id, role="admin")
            except User.DoesNotExist:
                raise ValidationError({"error": "Admin role required for API key generation"})

            # Verify target user exists
            try:
                User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise ValidationError({"error": "Target user not found"})

            # Generate cryptographically secure API key (32 bytes = 256 bits)
            api_key = secrets.token_urlsafe(32)
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()

            with transaction.atomic():
                # Create API key record
                api_key_obj = APIKey.objects.create(tenant_id=tenant_id, user_id=user_id, key_hash=key_hash)

                # Log API key creation
                AuditLogger.log_api_key_created(
                    tenant_id=tenant_id,
                    key_id=api_key_obj.id,
                    user_id=user_id,
                    created_by=requesting_user_id,
                )

                return {
                    "key_id": str(api_key_obj.id),
                    "api_key": api_key,  # Only returned once
                    "created_at": api_key_obj.created_at,
                }

        finally:
            clear_current_tenant()

    @staticmethod
    def revoke_api_key(tenant_id, key_id, requesting_user_id):
        """
        Revoke an API key

        Args:
            tenant_id: Tenant identifier
            key_id: API key ID to revoke
            requesting_user_id: User requesting the revocation

        Raises:
            ValidationError: If key not found or insufficient permissions
        """
        try:
            set_current_tenant(tenant_id)

            # Verify requesting user is admin
            try:
                User.objects.get(id=requesting_user_id, role="admin")
            except User.DoesNotExist:
                raise ValidationError({"error": "Admin role required for API key revocation"})

            # Find and revoke API key
            try:
                api_key = APIKey.objects.get(id=key_id, tenant_id=tenant_id)
            except APIKey.DoesNotExist:
                raise ValidationError({"error": "API key not found"})

            if api_key.revoked:
                raise ValidationError({"error": "API key is already revoked"})

            with transaction.atomic():
                # Revoke the key
                api_key.revoked = True
                api_key.revoked_at = timezone.now()
                api_key.save()

                # Log API key revocation
                AuditLogger.log_api_key_revoked(
                    tenant_id=tenant_id,
                    key_id=key_id,
                    revoked_by=requesting_user_id,
                )

        finally:
            clear_current_tenant()

    @staticmethod
    def authenticate_with_api_key(api_key):
        """
        Authenticate using API key

        Args:
            api_key: The API key string

        Returns:
            dict: {
                'user_id': str,
                'tenant_id': str,
                'role': str
            } or None if invalid
        """
        try:
            # Hash the API key
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()

            # Look up API key
            api_key_obj = (
                APIKey.objects.filter(key_hash=key_hash, revoked=False).select_related("user", "tenant").first()
            )

            if not api_key_obj:
                return None

            return {
                "user_id": str(api_key_obj.user.id),
                "tenant_id": api_key_obj.tenant_id,
                "role": api_key_obj.user.role,
            }

        except Exception:
            return None
