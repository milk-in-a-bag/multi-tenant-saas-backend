"""
Core models for audit logging and rate limiting
"""
from django.db import models
import uuid


class AuditLog(models.Model):
    """
    Audit log model for tracking security-relevant events
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='audit_logs',
        db_column='tenant_id'
    )
    event_type = models.CharField(max_length=100)
    user = models.ForeignKey(
        'authentication.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        db_column='user_id'
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        db_table = 'audit_logs'
        indexes = [
            models.Index(fields=['tenant', '-timestamp'], name='idx_audit_logs_tenant'),
            models.Index(fields=['timestamp'], name='idx_audit_logs_retention'),
        ]
    
    def __str__(self):
        return f"{self.event_type} at {self.timestamp}"


class RateLimit(models.Model):
    """
    Rate limit tracking model for per-tenant request throttling
    """
    tenant = models.OneToOneField(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='rate_limit',
        db_column='tenant_id'
    )
    request_count = models.IntegerField(default=0)
    window_start = models.DateTimeField()
    
    class Meta:
        db_table = 'rate_limits'
    
    def __str__(self):
        return f"RateLimit for {self.tenant_id}: {self.request_count} requests"
