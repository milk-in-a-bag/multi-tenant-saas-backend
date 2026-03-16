"""
Serializers for tenant management API
"""

from django.utils import timezone
from rest_framework import serializers


class TenantRegistrationSerializer(serializers.Serializer):
    """Serializer for tenant registration"""

    identifier = serializers.CharField(max_length=255, help_text="Unique tenant identifier")
    admin_email = serializers.EmailField(help_text="Email address for the admin user")
    admin_username = serializers.CharField(
        max_length=255, required=False, help_text="Username for admin user (optional, defaults to email prefix)"
    )

    def validate_identifier(self, value):
        """Validate tenant identifier format"""
        if not value.replace("-", "").replace("_", "").isalnum():
            raise serializers.ValidationError("Identifier can only contain letters, numbers, hyphens, and underscores")
        return value.lower()


class TenantDeletionSerializer(serializers.Serializer):
    """Serializer for tenant deletion"""

    password = serializers.CharField(write_only=True, help_text="Admin password for re-authentication")


class SubscriptionUpdateSerializer(serializers.Serializer):
    """Serializer for subscription updates"""

    TIER_CHOICES = [
        ("free", "Free"),
        ("professional", "Professional"),
        ("enterprise", "Enterprise"),
    ]

    tier = serializers.ChoiceField(choices=TIER_CHOICES, help_text="Subscription tier")
    expiration_date = serializers.DateTimeField(help_text="Subscription expiration date")

    def validate_expiration_date(self, value):
        """Validate expiration date is in the future"""
        if value <= timezone.now():
            raise serializers.ValidationError("Expiration date must be in the future")
        return value


class TenantConfigSerializer(serializers.Serializer):
    """Serializer for tenant configuration response"""

    tenant_id = serializers.CharField(read_only=True)
    subscription_tier = serializers.CharField(read_only=True)
    subscription_expiration = serializers.DateTimeField(read_only=True)
    rate_limit = serializers.IntegerField(read_only=True)
    status = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class AuditLogQuerySerializer(serializers.Serializer):
    """Serializer for audit log query parameters"""

    start_date = serializers.DateTimeField(required=False, help_text="Filter logs from this datetime (ISO 8601)")
    end_date = serializers.DateTimeField(required=False, help_text="Filter logs up to this datetime (ISO 8601)")
    page = serializers.IntegerField(required=False, default=1, min_value=1, help_text="Page number (default: 1)")
    page_size = serializers.IntegerField(
        required=False, default=50, min_value=1, max_value=200, help_text="Results per page (default: 50, max: 200)"
    )

    def validate(self, data):
        start = data.get("start_date")
        end = data.get("end_date")
        if start and end and start > end:
            raise serializers.ValidationError("start_date must be before end_date")
        return data
