"""
Tests for tenant management service
"""
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from rest_framework.exceptions import ValidationError

from .services import TenantManager
from .models import Tenant
from authentication.models import User
from core.models import AuditLog


class TenantManagerTest(TestCase):
    """Test cases for TenantManager service"""
    
    def test_register_tenant_success(self):
        """Test successful tenant registration"""
        result = TenantManager.register_tenant(
            identifier='test-company',
            admin_email='admin@test.com',
            admin_username='admin'
        )
        
        # Check return values
        self.assertEqual(result['tenant_id'], 'test-company')
        self.assertEqual(result['admin_username'], 'admin')
        self.assertIn('admin_password', result)
        
        # Check tenant was created
        tenant = Tenant.objects.get(id='test-company')
        self.assertEqual(tenant.subscription_tier, 'free')
        self.assertEqual(tenant.status, 'active')
        
        # Check admin user was created
        user = User.objects.get(tenant_id='test-company', username='admin')
        self.assertEqual(user.email, 'admin@test.com')
        self.assertEqual(user.role, 'admin')
        
        # Check audit log was created
        audit_log = AuditLog.objects.get(
            tenant_id='test-company',
            event_type='tenant_registered'
        )
        self.assertEqual(audit_log.details['tenant_id'], 'test-company')
    
    def test_register_duplicate_tenant_fails(self):
        """Test that duplicate tenant registration fails"""
        # Create first tenant
        TenantManager.register_tenant(
            identifier='test-company',
            admin_email='admin@test.com'
        )
        
        # Try to create duplicate
        with self.assertRaises(ValidationError) as context:
            TenantManager.register_tenant(
                identifier='test-company',
                admin_email='admin2@test.com'
            )
        
        self.assertIn('identifier', context.exception.detail)
    
    def test_get_tenant_config(self):
        """Test getting tenant configuration"""
        # Create tenant
        TenantManager.register_tenant(
            identifier='test-company',
            admin_email='admin@test.com'
        )
        
        # Get config
        config = TenantManager.get_tenant_config('test-company')
        
        self.assertEqual(config['tenant_id'], 'test-company')
        self.assertEqual(config['subscription_tier'], 'free')
        self.assertEqual(config['rate_limit'], 100)
        self.assertEqual(config['status'], 'active')
    
    def test_update_subscription(self):
        """Test updating subscription tier"""
        # Create tenant
        TenantManager.register_tenant(
            identifier='test-company',
            admin_email='admin@test.com'
        )
        
        # Update subscription
        new_expiration = timezone.now() + timedelta(days=30)
        TenantManager.update_subscription(
            tenant_id='test-company',
            tier='professional',
            expiration_date=new_expiration
        )
        
        # Check update
        config = TenantManager.get_tenant_config('test-company')
        self.assertEqual(config['subscription_tier'], 'professional')
        self.assertEqual(config['rate_limit'], 1000)
        
        # Check audit log
        audit_log = AuditLog.objects.get(
            tenant_id='test-company',
            event_type='subscription_updated'
        )
        self.assertEqual(audit_log.details['old_tier'], 'free')
        self.assertEqual(audit_log.details['new_tier'], 'professional')
    
    def test_delete_tenant_marks_pending(self):
        """Test that tenant deletion marks tenant as pending"""
        # Create tenant
        result = TenantManager.register_tenant(
            identifier='test-company',
            admin_email='admin@test.com'
        )
        
        # Get admin user
        admin_user = User.objects.get(
            tenant_id='test-company',
            role='admin'
        )
        
        # Delete tenant
        TenantManager.delete_tenant(
            tenant_id='test-company',
            admin_user_id=admin_user.id,
            password=result['admin_password']
        )
        
        # Check tenant status
        tenant = Tenant.objects.get(id='test-company')
        self.assertEqual(tenant.status, 'pending_deletion')
        
        # Check audit log
        audit_log = AuditLog.objects.get(
            tenant_id='test-company',
            event_type='tenant_deletion_requested'
        )
        self.assertEqual(audit_log.details['status'], 'pending_deletion')
    
    def test_check_pending_deletion_status(self):
        """Test checking pending deletion status"""
        # Create tenant
        result = TenantManager.register_tenant(
            identifier='test-company',
            admin_email='admin@test.com'
        )
        
        # Initially should be active
        self.assertTrue(
            TenantManager.check_pending_deletion_status('test-company')
        )
        
        # Mark for deletion
        admin_user = User.objects.get(
            tenant_id='test-company',
            role='admin'
        )
        TenantManager.delete_tenant(
            tenant_id='test-company',
            admin_user_id=admin_user.id,
            password=result['admin_password']
        )
        
        # Should now be pending deletion
        self.assertFalse(
            TenantManager.check_pending_deletion_status('test-company')
        )