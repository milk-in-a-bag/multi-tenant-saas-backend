"""
Tenant management service for handling tenant lifecycle operations
"""
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta
from django.utils import timezone
from django.db import transaction
from django.contrib.auth.hashers import make_password, check_password
from django.core.exceptions import ValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError

from .models import Tenant
from authentication.models import User
from core.models import AuditLog
from core.middleware import set_current_tenant, clear_current_tenant


class TenantManager:
    """
    Service class for managing tenant lifecycle operations including
    registration, deletion, and subscription management
    """
    
    @staticmethod
    def register_tenant(identifier, admin_email, admin_username=None):
        """
        Register a new tenant with admin user
        
        Args:
            identifier: Unique tenant identifier
            admin_email: Email for admin user
            admin_username: Optional username (defaults to email)
            
        Returns:
            dict: {
                'tenant_id': str,
                'admin_username': str,
                'admin_password': str  # Temporary password
            }
            
        Raises:
            ValidationError: If tenant identifier already exists
        """
        # Check if tenant already exists
        if Tenant.objects.filter(id=identifier).exists():
            raise DRFValidationError({
                'identifier': 'A tenant with this identifier already exists'
            })
        
        # Generate admin credentials
        if not admin_username:
            admin_username = admin_email.split('@')[0]
        
        # Generate secure temporary password
        temp_password = secrets.token_urlsafe(12)
        
        # Set default subscription expiration (1 year from now)
        default_expiration = timezone.now() + timedelta(days=365)
        
        try:
            with transaction.atomic():
                # Create tenant
                tenant = Tenant.objects.create(
                    id=identifier,
                    subscription_tier='free',
                    subscription_expiration=default_expiration,
                    status='active'
                )
                
                # Temporarily set tenant context for user creation
                set_current_tenant(identifier)
                
                # Create admin user with bcrypt cost factor 12
                admin_user = User.objects.create_user(
                    tenant_id=identifier,
                    username=admin_username,
                    email=admin_email,
                    password=temp_password,
                    role='admin'
                )
                
                # Log tenant registration
                AuditLog.objects.create(
                    tenant_id=identifier,
                    event_type='tenant_registered',
                    user_id=admin_user.id,
                    details={
                        'tenant_id': identifier,
                        'admin_username': admin_username,
                        'admin_email': admin_email,
                        'subscription_tier': 'free'
                    }
                )
                
                return {
                    'tenant_id': identifier,
                    'admin_username': admin_username,
                    'admin_password': temp_password
                }
                
        except Exception as e:
            # Clear tenant context on error
            clear_current_tenant()
            raise e
        finally:
            # Always clear tenant context
            clear_current_tenant()
    
    @staticmethod
    def delete_tenant(tenant_id, admin_user_id, password):
        """
        Delete a tenant after password re-authentication
        
        Args:
            tenant_id: ID of tenant to delete
            admin_user_id: ID of admin user requesting deletion
            password: Password for re-authentication
            
        Raises:
            ValidationError: If re-authentication fails or user is not admin
        """
        try:
            # Set tenant context for operations
            set_current_tenant(tenant_id)
            
            # Get the admin user and verify password
            try:
                admin_user = User.objects.get(id=admin_user_id, role='admin')
            except User.DoesNotExist:
                raise DRFValidationError({
                    'error': 'Admin user not found or insufficient permissions'
                })
            
            # Verify password for re-authentication
            if not admin_user.check_password(password):
                raise DRFValidationError({
                    'password': 'Invalid password for re-authentication'
                })
            
            with transaction.atomic():
                # Get tenant
                try:
                    tenant = Tenant.objects.get(id=tenant_id)
                except Tenant.DoesNotExist:
                    raise DRFValidationError({
                        'tenant_id': 'Tenant not found'
                    })
                
                # Mark tenant as pending deletion
                tenant.status = 'pending_deletion'
                tenant.save()
                
                # Log deletion event
                AuditLog.objects.create(
                    tenant_id=tenant_id,
                    event_type='tenant_deletion_requested',
                    user_id=admin_user_id,
                    details={
                        'tenant_id': tenant_id,
                        'admin_user_id': str(admin_user_id),
                        'status': 'pending_deletion'
                    }
                )
                
        finally:
            clear_current_tenant()
    
    @staticmethod
    def update_subscription(tenant_id, tier, expiration_date):
        """
        Update tenant subscription tier and expiration
        
        Args:
            tenant_id: ID of tenant to update
            tier: New subscription tier ('free', 'professional', 'enterprise')
            expiration_date: New expiration date
            
        Raises:
            ValidationError: If tenant not found or invalid tier
        """
        valid_tiers = ['free', 'professional', 'enterprise']
        if tier not in valid_tiers:
            raise DRFValidationError({
                'tier': f'Invalid subscription tier. Must be one of: {valid_tiers}'
            })
        
        try:
            # Set tenant context
            set_current_tenant(tenant_id)
            
            with transaction.atomic():
                # Get tenant
                try:
                    tenant = Tenant.objects.get(id=tenant_id)
                except Tenant.DoesNotExist:
                    raise DRFValidationError({
                        'tenant_id': 'Tenant not found'
                    })
                
                # Store old values for audit log
                old_tier = tenant.subscription_tier
                old_expiration = tenant.subscription_expiration
                
                # Update subscription
                tenant.subscription_tier = tier
                tenant.subscription_expiration = expiration_date
                tenant.save()
                
                # Log subscription change
                AuditLog.objects.create(
                    tenant_id=tenant_id,
                    event_type='subscription_updated',
                    details={
                        'tenant_id': tenant_id,
                        'old_tier': old_tier,
                        'new_tier': tier,
                        'old_expiration': old_expiration.isoformat(),
                        'new_expiration': expiration_date.isoformat()
                    }
                )
                
        finally:
            clear_current_tenant()
    
    @staticmethod
    def get_tenant_config(tenant_id):
        """
        Get tenant configuration including subscription details
        
        Args:
            tenant_id: ID of tenant to retrieve
            
        Returns:
            dict: Tenant configuration data
            
        Raises:
            ValidationError: If tenant not found
        """
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            raise DRFValidationError({
                'tenant_id': 'Tenant not found'
            })
        
        # Check if subscription is expired and downgrade if needed
        if (tenant.subscription_expiration < timezone.now() and 
            tenant.subscription_tier != 'free'):
            
            # Auto-downgrade expired subscription
            TenantManager.update_subscription(
                tenant_id, 
                'free', 
                tenant.subscription_expiration
            )
            tenant.refresh_from_db()
        
        # Get rate limit based on subscription tier
        rate_limits = {
            'free': 100,
            'professional': 1000,
            'enterprise': 10000
        }
        
        return {
            'tenant_id': tenant.id,
            'subscription_tier': tenant.subscription_tier,
            'subscription_expiration': tenant.subscription_expiration,
            'rate_limit': rate_limits.get(tenant.subscription_tier, 100),
            'status': tenant.status,
            'created_at': tenant.created_at
        }
    
    @staticmethod
    def check_pending_deletion_status(tenant_id):
        """
        Check if tenant is pending deletion and reject API requests
        
        Args:
            tenant_id: ID of tenant to check
            
        Returns:
            bool: True if tenant can make requests, False if pending deletion
        """
        try:
            tenant = Tenant.objects.get(id=tenant_id)
            return tenant.status != 'pending_deletion'
        except Tenant.DoesNotExist:
            return False