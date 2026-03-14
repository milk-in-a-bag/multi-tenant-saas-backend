"""
Widget model - example tenant-isolated business entity
"""
import uuid
from django.db import models
from core.data_isolator import TenantIsolatedModel


class Widget(TenantIsolatedModel):
    """
    Example business entity demonstrating tenant-isolated CRUD operations.
    Follows the same patterns used throughout the multi-tenant infrastructure.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='widgets',
        db_column='tenant_id'
    )
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='widgets',
        db_column='created_by'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'widgets'
        unique_together = [('tenant', 'name')]
        indexes = [
            models.Index(fields=['tenant'], name='idx_widgets_tenant'),
            models.Index(fields=['tenant', 'name'], name='idx_widgets_name'),
            models.Index(fields=['tenant', '-created_at'], name='idx_widgets_created_at'),
        ]

    def __str__(self):
        return f"Widget '{self.name}' ({self.tenant_id})"
