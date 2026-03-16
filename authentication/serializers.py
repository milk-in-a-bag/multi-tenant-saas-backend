"""
Serializers for authentication API
"""

from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    """Serializer for user login"""

    tenant_id = serializers.CharField(max_length=255, help_text="Tenant identifier")
    username = serializers.CharField(max_length=255, help_text="Username or email address")
    password = serializers.CharField(write_only=True, help_text="User password")
