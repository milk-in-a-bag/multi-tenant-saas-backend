"""
Widget serializers for input validation and response formatting
"""
from rest_framework import serializers
from .models import Widget


class WidgetCreateSerializer(serializers.Serializer):
    """Validates input for widget creation"""
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    metadata = serializers.JSONField(required=False, default=dict)

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError('Name cannot be blank.')
        return value.strip()


class WidgetUpdateSerializer(serializers.Serializer):
    """Validates input for widget updates (all fields optional)"""
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    metadata = serializers.JSONField(required=False)

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError('Name cannot be blank.')
        return value.strip()


class WidgetSerializer(serializers.ModelSerializer):
    """Response serializer for Widget instances"""
    tenant_id = serializers.CharField(source='tenant_id')
    created_by = serializers.UUIDField(source='created_by_id')

    class Meta:
        model = Widget
        fields = [
            'id', 'tenant_id', 'name', 'description',
            'metadata', 'created_by', 'created_at', 'updated_at',
        ]
        read_only_fields = fields


class WidgetFilterSerializer(serializers.Serializer):
    """Validates query parameters for widget list endpoint"""
    name_contains = serializers.CharField(required=False)
    created_after = serializers.DateTimeField(required=False)
    created_before = serializers.DateTimeField(required=False)
    page = serializers.IntegerField(required=False, default=1, min_value=1)
    page_size = serializers.IntegerField(required=False, default=20, min_value=1, max_value=100)

    def validate(self, data):
        after = data.get('created_after')
        before = data.get('created_before')
        if after and before and after > before:
            raise serializers.ValidationError('created_after must be before created_before.')
        return data
