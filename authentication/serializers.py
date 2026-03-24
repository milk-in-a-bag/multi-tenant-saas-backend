"""
Serializers for authentication API
"""

from rest_framework import serializers


class LoginSerializer(serializers.Serializer):
    """Serializer for user login"""

    tenant_id = serializers.CharField(max_length=255, help_text="Tenant identifier")
    username = serializers.CharField(max_length=255, help_text="Username or email address")
    password = serializers.CharField(write_only=True, help_text="User password")


class UpdateProfileSerializer(serializers.Serializer):
    """Serializer for updating own profile (username and/or password)"""

    username = serializers.CharField(max_length=255, required=False, help_text="New username")
    current_password = serializers.CharField(write_only=True, required=False, help_text="Current password (required when changing password)")
    new_password = serializers.CharField(write_only=True, required=False, min_length=8, help_text="New password (min 8 characters)")

    def validate(self, data):
        # If new_password is provided, current_password must also be provided
        if data.get("new_password") and not data.get("current_password"):
            raise serializers.ValidationError({"current_password": "Current password is required to set a new password."})
        return data
