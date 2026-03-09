"""
User and authentication models
"""
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
import uuid


class UserManager(BaseUserManager):
    """Custom user manager"""
    
    def create_user(self, tenant_id, username, email, password=None, **extra_fields):
        if not tenant_id:
            raise ValueError('User must have a tenant')
        if not username:
            raise ValueError('User must have a username')
        if not email:
            raise ValueError('User must have an email')
        
        email = self.normalize_email(email)
        user = self.model(
            tenant_id=tenant_id,
            username=username,
            email=email,
            **extra_fields
        )
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, tenant_id, username, email, password=None, **extra_fields):
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(tenant_id, username, email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model with tenant isolation
    """
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('user', 'User'),
        ('read_only', 'Read Only'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='users',
        db_column='tenant_id'
    )
    username = models.CharField(max_length=255)
    email = models.EmailField(max_length=255)
    password = models.CharField(max_length=255)
    role = models.CharField(
        max_length=50,
        choices=ROLE_CHOICES,
        default='user'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'id'
    REQUIRED_FIELDS = ['username', 'email']
    
    class Meta:
        db_table = 'users'
        unique_together = [
            ('tenant', 'username'),
            ('tenant', 'email'),
        ]
        indexes = [
            models.Index(fields=['tenant'], name='idx_users_tenant'),
            models.Index(fields=['tenant', 'email'], name='idx_users_email'),
        ]
    
    def __str__(self):
        return f"{self.username} ({self.tenant_id})"


class APIKey(models.Model):
    """
    API key model for programmatic access
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='api_keys',
        db_column='tenant_id'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='api_keys',
        db_column='user_id'
    )
    key_hash = models.CharField(max_length=255, unique=True)
    revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'api_keys'
        indexes = [
            models.Index(fields=['tenant'], name='idx_api_keys_tenant'),
            models.Index(
                fields=['key_hash'],
                name='idx_api_keys_hash',
                condition=models.Q(revoked=False)
            ),
        ]
    
    def __str__(self):
        return f"APIKey {self.id} for {self.user.username}"
