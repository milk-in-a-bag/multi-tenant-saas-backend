# Extension Point: Custom Authorization Rules

**Requirement: 13.2**

This document explains how to add custom authorization logic beyond the built-in role-based access control (RBAC).

---

## Overview

The system ships with three roles and a fixed permission matrix:

| Role        | read | write | delete | admin |
| ----------- | ---- | ----- | ------ | ----- |
| `admin`     | ✓    | ✓     | ✓      | ✓     |
| `user`      | ✓    | ✓     | ✗      | ✗     |
| `read_only` | ✓    | ✗     | ✗      | ✗     |

This is enforced by `AuthService.authorize_operation` in `authentication/services.py` and the DRF permission classes in `authentication/permissions.py`.

You can extend authorization in three ways:

1. **Add new operations** — extend `OPERATION_PERMISSIONS` in `AuthService`
2. **Add new permission classes** — subclass `BasePermission` for resource-level or attribute-based rules
3. **Add object-level permissions** — implement `has_object_permission` for row-level access control

---

## Where to Make Changes

| File                            | What to change                                                  |
| ------------------------------- | --------------------------------------------------------------- |
| `authentication/services.py`    | Extend `OPERATION_PERMISSIONS` or add new authorization methods |
| `authentication/permissions.py` | Add new DRF permission classes                                  |
| `<app>/views.py`                | Apply new permission classes to specific views                  |

---

## Extension Point Marker

```python
# EXTENSION_POINT: authorization-rules
# Add custom authorization logic here.
# Options:
#   1. Extend OPERATION_PERMISSIONS to add new operation types
#   2. Add new DRF permission classes in authentication/permissions.py
#   3. Implement has_object_permission for row-level access control
# See: docs/extension-points/authorization-rules.md
```

This comment lives in `authentication/services.py` above `OPERATION_PERMISSIONS`.

---

## Example 1: Adding a New Operation Type

The built-in operations are `read`, `write`, `delete`, and `admin`. To add a custom operation (e.g., `export`):

```python
# authentication/services.py

class AuthService:
    # EXTENSION_POINT: authorization-rules
    OPERATION_PERMISSIONS = {
        "admin":     ["read", "write", "delete", "admin", "export"],
        "user":      ["read", "write", "export"],   # users can export
        "read_only": ["read"],                       # read_only cannot export
    }
```

Then use it in a view:

```python
# widgets/views.py

from authentication.permissions import RoleBasedPermission

class WidgetExportView(APIView):
    permission_classes = [RoleBasedPermission]
    required_operation = "export"   # checked against OPERATION_PERMISSIONS

    def get(self, request):
        # Only admin and user roles reach here
        ...
```

---

## Example 2: Attribute-Based Access Control (ABAC)

For rules that depend on resource attributes (e.g., "users can only edit their own widgets"):

```python
# authentication/permissions.py

from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Object-level permission: allow access only if the requesting user
    created the object, or has the admin role.

    Apply to any view that operates on a single object.
    """

    def has_object_permission(self, request, view, obj):
        # Admins can always access
        if request.user.role == "admin":
            return True

        # Check if the object was created by this user
        # Assumes the model has a `created_by` field (like Widget)
        if hasattr(obj, "created_by_id"):
            if obj.created_by_id == request.user.id:
                return True

        raise PermissionDenied({
            "error": {
                "code": "INSUFFICIENT_PERMISSIONS",
                "message": "You can only modify resources you created.",
            }
        })
```

Apply it in a view:

```python
# widgets/views.py

from authentication.permissions import RoleBasedPermission, IsOwnerOrAdmin

class WidgetDetailView(RetrieveUpdateDestroyAPIView):
    permission_classes = [RoleBasedPermission, IsOwnerOrAdmin]

    def get_object(self):
        obj = super().get_object()
        self.check_object_permissions(self.request, obj)  # triggers has_object_permission
        return obj
```

---

## Example 3: Subscription-Tier-Based Authorization

Restrict certain operations to tenants on higher subscription tiers:

```python
# authentication/permissions.py

from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied
from tenants.models import Tenant


class RequiresProfessionalTier(permissions.BasePermission):
    """
    Deny access unless the tenant is on the professional or enterprise tier.
    Use this to gate premium features.
    """

    def has_permission(self, request, view):
        tenant_id = getattr(request.user, "tenant_id", None)
        if not tenant_id:
            return False

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            return False

        if tenant.subscription_tier in ("professional", "enterprise"):
            return True

        raise PermissionDenied({
            "error": {
                "code": "SUBSCRIPTION_REQUIRED",
                "message": "This feature requires a Professional or Enterprise subscription.",
            }
        })
```

---

## Example 4: Time-Based Access Control

Restrict access to business hours only (useful for compliance scenarios):

```python
# authentication/permissions.py

from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied
from django.utils import timezone


class BusinessHoursOnly(permissions.BasePermission):
    """
    Allow write operations only during business hours (Mon–Fri, 09:00–17:00 UTC).
    Read operations are always allowed.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True  # reads are always allowed

        now = timezone.now()
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            raise PermissionDenied({
                "error": {
                    "code": "OUTSIDE_BUSINESS_HOURS",
                    "message": "Write operations are only permitted Monday–Friday.",
                }
            })

        if not (9 <= now.hour < 17):
            raise PermissionDenied({
                "error": {
                    "code": "OUTSIDE_BUSINESS_HOURS",
                    "message": "Write operations are only permitted 09:00–17:00 UTC.",
                }
            })

        return True
```

---

## Combining Permission Classes

DRF evaluates `permission_classes` as a logical AND — all classes must pass:

```python
class SensitiveReportView(APIView):
    permission_classes = [
        RoleBasedPermission,          # must have correct role
        RequiresProfessionalTier,     # must be on paid tier
        BusinessHoursOnly,            # must be within business hours
    ]
    required_operation = "admin"
```

---

## Testing Custom Authorization Rules

```python
# authentication/tests.py

from django.test import TestCase
from rest_framework.test import APIRequestFactory
from rest_framework.exceptions import PermissionDenied
from authentication.permissions import IsOwnerOrAdmin, RequiresProfessionalTier
from authentication.models import User
from tenants.models import Tenant
from widgets.models import Widget
from django.utils import timezone
from datetime import timedelta
import uuid


class IsOwnerOrAdminTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            id="test-tenant",
            subscription_tier="free",
            subscription_expiration=timezone.now() + timedelta(days=365),
        )
        self.factory = APIRequestFactory()
        self.permission = IsOwnerOrAdmin()

    def _make_user(self, role):
        from core.middleware import set_current_tenant
        set_current_tenant("test-tenant")
        return User.objects.create_user(
            tenant_id="test-tenant",
            username=f"user-{uuid.uuid4().hex[:6]}",
            email=f"{uuid.uuid4().hex[:6]}@example.com",
            password="pass",
            role=role,
        )

    def test_admin_can_access_any_object(self):
        admin = self._make_user("admin")
        owner = self._make_user("user")
        request = self.factory.get("/")
        request.user = admin

        widget = Widget(tenant_id="test-tenant", created_by=owner)
        # Should not raise
        result = self.permission.has_object_permission(request, None, widget)
        self.assertTrue(result)

    def test_user_can_access_own_object(self):
        user = self._make_user("user")
        request = self.factory.get("/")
        request.user = user

        widget = Widget(tenant_id="test-tenant", created_by=user)
        result = self.permission.has_object_permission(request, None, widget)
        self.assertTrue(result)

    def test_user_cannot_access_others_object(self):
        user = self._make_user("user")
        other = self._make_user("user")
        request = self.factory.patch("/")
        request.user = user

        widget = Widget(tenant_id="test-tenant", created_by=other)
        with self.assertRaises(PermissionDenied):
            self.permission.has_object_permission(request, None, widget)
```

---

## Related Files

- `authentication/permissions.py` — `RoleBasedPermission`, `IsAdmin`, `IsAdminOrUser`
- `authentication/services.py` — `AuthService.authorize_operation`, `OPERATION_PERMISSIONS`
- `docs/developer-guide/architecture.md` — RBAC table and request flow diagram
