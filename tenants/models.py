"""
Tenant models for multi-tenant isolation
"""

from django.db import models


class Tenant(models.Model):
    """
    Tenant model representing an isolated customer organization
    """

    SUBSCRIPTION_TIERS = [
        ("free", "Free"),
        ("professional", "Professional"),
        ("enterprise", "Enterprise"),
    ]

    # EXTENSION_POINT: subscription-features
    # Add new subscription tiers or feature flags by extending SUBSCRIPTION_TIERS
    # and adding a corresponding entry in RateLimitMiddleware.TIER_LIMITS.
    # To gate features per tier, define a TIER_FEATURES dict mapping tier names
    # to sets of feature keys and check it in your views or services.
    # See: docs/extension-points/subscription-features.md

    STATUS_CHOICES = [
        ("active", "Active"),
        ("pending_deletion", "Pending Deletion"),
        ("deleted", "Deleted"),
    ]

    id = models.CharField(max_length=255, primary_key=True)
    subscription_tier = models.CharField(max_length=50, choices=SUBSCRIPTION_TIERS, default="free")
    subscription_expiration = models.DateTimeField()
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="active")
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tenants"
        indexes = [
            models.Index(fields=["status"], name="idx_tenants_status"),
        ]

    def __str__(self):
        return f"Tenant {self.id} ({self.subscription_tier})"
