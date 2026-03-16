"""
Unit tests for authentication service
"""

from datetime import timedelta

import pytest
from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from authentication.models import APIKey, User
from authentication.services import AuthService
from core.models import AuditLog
from tenants.models import Tenant


@pytest.mark.django_db
class TestAuthService(TestCase):
    """Test cases for AuthService"""

    def setUp(self):
        """Set up test data"""
        # Create tenant
        self.tenant = Tenant.objects.create(
            id="test-tenant",
            subscription_tier="free",
            subscription_expiration=timezone.now() + timedelta(days=365),
            status="active",
        )

        # Create admin user
        self.admin_user = User.objects.create(
            tenant=self.tenant, username="admin", email="admin@test.com", role="admin"
        )
        self.admin_user.set_password("password123")
        self.admin_user.save()

        # Create regular user
        self.regular_user = User.objects.create(tenant=self.tenant, username="user", email="user@test.com", role="user")
        self.regular_user.set_password("password456")
        self.regular_user.save()

    def test_authenticate_user_with_username(self):
        """Test successful authentication with username"""
        result = AuthService.authenticate_user(
            tenant_id="test-tenant", username="admin", password="password123", ip_address="127.0.0.1"
        )

        self.assertIn("access_token", result)
        self.assertIn("refresh_token", result)
        self.assertEqual(result["user_id"], str(self.admin_user.id))
        self.assertEqual(result["tenant_id"], "test-tenant")
        self.assertEqual(result["role"], "admin")

        # Verify audit log was created
        audit_log = AuditLog.objects.filter(tenant_id="test-tenant", event_type="authentication_success").first()
        self.assertIsNotNone(audit_log)

    def test_authenticate_user_with_email(self):
        """Test successful authentication with email"""
        result = AuthService.authenticate_user(
            tenant_id="test-tenant", username="user@test.com", password="password456", ip_address="127.0.0.1"
        )

        self.assertIn("access_token", result)
        self.assertEqual(result["user_id"], str(self.regular_user.id))
        self.assertEqual(result["role"], "user")

    def test_authenticate_invalid_username(self):
        """Test authentication with invalid username returns generic error"""
        with self.assertRaises(ValidationError) as context:
            AuthService.authenticate_user(
                tenant_id="test-tenant", username="nonexistent", password="password123", ip_address="127.0.0.1"
            )

        self.assertIn("error", context.exception.detail)
        self.assertEqual(context.exception.detail["error"], "Invalid credentials")

        # Verify failed authentication was logged
        audit_log = AuditLog.objects.filter(tenant_id="test-tenant", event_type="authentication_failed").first()
        self.assertIsNotNone(audit_log)

    def test_authenticate_invalid_password(self):
        """Test authentication with invalid password returns generic error"""
        with self.assertRaises(ValidationError) as context:
            AuthService.authenticate_user(
                tenant_id="test-tenant", username="admin", password="wrongpassword", ip_address="127.0.0.1"
            )

        self.assertIn("error", context.exception.detail)
        self.assertEqual(context.exception.detail["error"], "Invalid credentials")

    def test_validate_token_success(self):
        """Test JWT token validation with valid token"""
        # Authenticate to get a token
        auth_result = AuthService.authenticate_user(tenant_id="test-tenant", username="admin", password="password123")

        # Validate the token
        validation_result = AuthService.validate_token(auth_result["access_token"])

        # Debug output
        if not validation_result["valid"]:
            print(f"Token validation failed: {validation_result.get('error')}")

        self.assertTrue(validation_result["valid"])
        self.assertEqual(validation_result["user_id"], str(self.admin_user.id))
        self.assertEqual(validation_result["tenant_id"], "test-tenant")
        self.assertEqual(validation_result["role"], "admin")
        self.assertIsNotNone(validation_result["expires_at"])

    def test_validate_token_invalid(self):
        """Test JWT token validation with invalid token"""
        validation_result = AuthService.validate_token("invalid.token.here")

        self.assertFalse(validation_result["valid"])
        self.assertIn("error", validation_result)

    def test_generate_api_key_success(self):
        """Test API key generation by admin user"""
        result = AuthService.generate_api_key(
            tenant_id="test-tenant", user_id=str(self.regular_user.id), requesting_user_id=str(self.admin_user.id)
        )

        self.assertIn("key_id", result)
        self.assertIn("api_key", result)
        self.assertIn("created_at", result)

        # Verify API key was created in database
        api_key = APIKey.objects.filter(id=result["key_id"]).first()
        self.assertIsNotNone(api_key)
        self.assertEqual(api_key.user_id, self.regular_user.id)
        self.assertFalse(api_key.revoked)

        # Verify audit log was created
        audit_log = AuditLog.objects.filter(tenant_id="test-tenant", event_type="api_key_created").first()
        self.assertIsNotNone(audit_log)

    def test_generate_api_key_non_admin_fails(self):
        """Test API key generation fails for non-admin user"""
        with self.assertRaises(ValidationError) as context:
            AuthService.generate_api_key(
                tenant_id="test-tenant", user_id=str(self.regular_user.id), requesting_user_id=str(self.regular_user.id)
            )

        self.assertIn("error", context.exception.detail)
        self.assertIn("Admin role required", context.exception.detail["error"])

    def test_authenticate_with_api_key_success(self):
        """Test authentication with valid API key"""
        # Generate API key
        key_result = AuthService.generate_api_key(
            tenant_id="test-tenant", user_id=str(self.regular_user.id), requesting_user_id=str(self.admin_user.id)
        )

        # Authenticate with API key
        auth_result = AuthService.authenticate_with_api_key(key_result["api_key"])

        self.assertIsNotNone(auth_result)
        self.assertEqual(auth_result["user_id"], str(self.regular_user.id))
        self.assertEqual(auth_result["tenant_id"], "test-tenant")
        self.assertEqual(auth_result["role"], "user")

    def test_authenticate_with_invalid_api_key(self):
        """Test authentication with invalid API key"""
        auth_result = AuthService.authenticate_with_api_key("invalid-key")

        self.assertIsNone(auth_result)

    def test_revoke_api_key_success(self):
        """Test API key revocation by admin user"""
        # Generate API key
        key_result = AuthService.generate_api_key(
            tenant_id="test-tenant", user_id=str(self.regular_user.id), requesting_user_id=str(self.admin_user.id)
        )

        # Revoke the key
        AuthService.revoke_api_key(
            tenant_id="test-tenant", key_id=key_result["key_id"], requesting_user_id=str(self.admin_user.id)
        )

        # Verify key is revoked
        api_key = APIKey.objects.get(id=key_result["key_id"])
        self.assertTrue(api_key.revoked)
        self.assertIsNotNone(api_key.revoked_at)

        # Verify authentication with revoked key fails
        auth_result = AuthService.authenticate_with_api_key(key_result["api_key"])
        self.assertIsNone(auth_result)

        # Verify audit log was created
        audit_log = AuditLog.objects.filter(tenant_id="test-tenant", event_type="api_key_revoked").first()
        self.assertIsNotNone(audit_log)

    def test_revoke_api_key_non_admin_fails(self):
        """Test API key revocation fails for non-admin user"""
        # Generate API key
        key_result = AuthService.generate_api_key(
            tenant_id="test-tenant", user_id=str(self.regular_user.id), requesting_user_id=str(self.admin_user.id)
        )

        # Try to revoke as non-admin
        with self.assertRaises(ValidationError) as context:
            AuthService.revoke_api_key(
                tenant_id="test-tenant", key_id=key_result["key_id"], requesting_user_id=str(self.regular_user.id)
            )

        self.assertIn("error", context.exception.detail)
        self.assertIn("Admin role required", context.exception.detail["error"])

    def test_jwt_expiration_is_one_hour(self):
        """Test that JWT token expiration is set to 1 hour (3600 seconds)"""
        # Authenticate to get a token
        auth_result = AuthService.authenticate_user(tenant_id="test-tenant", username="admin", password="password123")

        # Validate the token to get expiration
        validation_result = AuthService.validate_token(auth_result["access_token"])

        self.assertTrue(validation_result["valid"])

        # Calculate time difference between now and expiration
        now = timezone.now()
        expires_at = validation_result["expires_at"]
        time_diff = (expires_at - now).total_seconds()

        # Should be approximately 1 hour (3600 seconds), allow 5 second tolerance
        self.assertAlmostEqual(time_diff, 3600, delta=5)


@pytest.mark.django_db
class TestAuthorizationService(TestCase):
    """Test cases for authorization (RBAC) functionality"""

    def test_admin_role_permits_all_operations(self):
        """Test that admin role permits all operations"""
        self.assertTrue(AuthService.authorize_operation("admin", "read"))
        self.assertTrue(AuthService.authorize_operation("admin", "write"))
        self.assertTrue(AuthService.authorize_operation("admin", "delete"))
        self.assertTrue(AuthService.authorize_operation("admin", "admin"))

    def test_user_role_permits_read_and_write_only(self):
        """Test that user role permits read and write but not delete or admin"""
        self.assertTrue(AuthService.authorize_operation("user", "read"))
        self.assertTrue(AuthService.authorize_operation("user", "write"))
        self.assertFalse(AuthService.authorize_operation("user", "delete"))
        self.assertFalse(AuthService.authorize_operation("user", "admin"))

    def test_read_only_role_permits_only_reads(self):
        """Test that read_only role permits only read operations"""
        self.assertTrue(AuthService.authorize_operation("read_only", "read"))
        self.assertFalse(AuthService.authorize_operation("read_only", "write"))
        self.assertFalse(AuthService.authorize_operation("read_only", "delete"))
        self.assertFalse(AuthService.authorize_operation("read_only", "admin"))

    def test_invalid_role_denies_all_operations(self):
        """Test that invalid role defaults to denying all operations"""
        self.assertFalse(AuthService.authorize_operation("invalid_role", "read"))
        self.assertFalse(AuthService.authorize_operation("invalid_role", "write"))
        self.assertFalse(AuthService.authorize_operation("invalid_role", "delete"))
        self.assertFalse(AuthService.authorize_operation("invalid_role", "admin"))

    def test_missing_role_denies_all_operations(self):
        """Test that missing role defaults to denying all operations"""
        self.assertFalse(AuthService.authorize_operation(None, "read"))
        self.assertFalse(AuthService.authorize_operation("", "read"))
