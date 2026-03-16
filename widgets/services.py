"""
Widget service - example tenant-isolated CRUD business logic.
Demonstrates the standard patterns for building resources on this platform.
"""

from django.db import IntegrityError
from rest_framework.exceptions import NotFound, ValidationError

from .models import Widget


class WidgetService:
    """
    Service class for Widget CRUD operations.
    All methods enforce tenant isolation via the TenantIsolatedModel manager.
    """

    @staticmethod
    def create_widget(tenant_id, user_id, name, description=None, metadata=None):
        """
        Create a new widget for the given tenant.

        Args:
            tenant_id: Authenticated tenant's ID (set in thread-local context)
            user_id: ID of the user creating the widget
            name: Widget name (required, unique within tenant)
            description: Optional text description
            metadata: Optional JSON metadata dict

        Returns:
            Widget instance

        Raises:
            ValidationError: If name is missing or already exists within tenant
        """
        if not name or not name.strip():
            raise ValidationError({"name": "This field is required."})

        try:
            widget = Widget.objects.create(
                tenant_id=tenant_id,
                name=name.strip(),
                description=description,
                metadata=metadata or {},
                created_by_id=user_id,
            )
        except IntegrityError:
            raise ValidationError({"name": f"A widget named '{name}' already exists in this tenant."})

        return widget

    @staticmethod
    def get_widget(tenant_id, widget_id):
        """
        Retrieve a single widget by ID, scoped to the tenant.

        Raises:
            NotFound: If widget does not exist or belongs to another tenant
        """
        try:
            return Widget.objects.get(id=widget_id, tenant_id=tenant_id)
        except Widget.DoesNotExist:
            raise NotFound({"detail": "Widget not found."})

    @staticmethod
    def list_widgets(tenant_id, name_contains=None, created_after=None, created_before=None):
        """
        List all widgets for the tenant with optional filters.

        Args:
            tenant_id: Authenticated tenant's ID
            name_contains: Optional substring filter on name
            created_after: Optional datetime lower bound
            created_before: Optional datetime upper bound

        Returns:
            QuerySet of Widget instances
        """
        qs = Widget.objects.filter(tenant_id=tenant_id).order_by("-created_at")

        if name_contains:
            qs = qs.filter(name__icontains=name_contains)
        if created_after:
            qs = qs.filter(created_at__gte=created_after)
        if created_before:
            qs = qs.filter(created_at__lte=created_before)

        return qs

    @staticmethod
    def update_widget(tenant_id, widget_id, name=None, description=None, metadata=None):
        """
        Update a widget, verifying it belongs to the tenant.

        Raises:
            NotFound: If widget does not exist for this tenant
            ValidationError: If new name conflicts with an existing widget
        """
        widget = WidgetService.get_widget(tenant_id, widget_id)

        if name is not None:
            if not name.strip():
                raise ValidationError({"name": "Name cannot be blank."})
            widget.name = name.strip()

        if description is not None:
            widget.description = description

        if metadata is not None:
            widget.metadata = metadata

        try:
            widget.save()
        except IntegrityError:
            raise ValidationError({"name": f"A widget named '{name}' already exists in this tenant."})

        return widget

    @staticmethod
    def delete_widget(tenant_id, widget_id):
        """
        Delete a widget, verifying it belongs to the tenant.

        Raises:
            NotFound: If widget does not exist for this tenant
        """
        widget = WidgetService.get_widget(tenant_id, widget_id)
        widget.delete()
