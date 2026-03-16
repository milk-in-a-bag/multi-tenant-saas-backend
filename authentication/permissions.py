"""
DRF permission classes for role-based access control
"""

# EXTENSION_POINT: authorization-rules
# Add custom DRF permission classes by subclassing BasePermission.
# Override has_permission(request, view) and/or has_object_permission(request, view, obj)
# to implement attribute-based access control (ABAC), resource ownership checks,
# or tenant-scoped policies.
# See: docs/extension-points/authorization-rules.md
from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied

from .services import AuthService


class RoleBasedPermission(permissions.BasePermission):
    """
    Permission class that checks role-based access control

    Usage in views:
        permission_classes = [RoleBasedPermission]
        required_operation = 'read'  # or 'write', 'delete', 'admin'
    """

    def has_permission(self, request, view):
        """
        Check if the user has permission to perform the requested operation
        """
        # Check if user is authenticated
        if not request.user or not request.user.is_authenticated:
            return False

        # Get the required operation from the view
        # Default to 'read' for GET/HEAD/OPTIONS, 'write' for POST/PUT/PATCH, 'delete' for DELETE
        required_operation = getattr(view, "required_operation", None)

        if required_operation is None:
            # Auto-detect operation based on HTTP method
            if request.method in ["GET", "HEAD", "OPTIONS"]:
                required_operation = "read"
            elif request.method in ["POST", "PUT", "PATCH"]:
                required_operation = "write"
            elif request.method == "DELETE":
                required_operation = "delete"
            else:
                required_operation = "read"

        # Get user role from request.user
        user_role = getattr(request.user, "role", None)

        if not user_role:
            return False

        # Check authorization
        authorized = AuthService.authorize_operation(user_role, required_operation)

        if not authorized:
            # Raise PermissionDenied with a clear message
            raise PermissionDenied(
                {
                    "error": {
                        "code": "INSUFFICIENT_PERMISSIONS",
                        "message": f"Your role ({user_role}) does not permit {required_operation} operations",
                    }
                }
            )

        return True


class IsAdmin(permissions.BasePermission):
    """
    Permission class that only allows admin users
    """

    def has_permission(self, request, view):
        """Check if user has admin role"""
        if not request.user or not request.user.is_authenticated:
            return False

        user_role = getattr(request.user, "role", None)

        if user_role != "admin":
            raise PermissionDenied(
                {"error": {"code": "ADMIN_REQUIRED", "message": "This operation requires admin role"}}
            )

        return True


class IsAdminOrUser(permissions.BasePermission):
    """
    Permission class that allows admin and user roles (excludes read_only)
    """

    def has_permission(self, request, view):
        """Check if user has admin or user role"""
        if not request.user or not request.user.is_authenticated:
            return False

        user_role = getattr(request.user, "role", None)

        if user_role not in ["admin", "user"]:
            raise PermissionDenied(
                {"error": {"code": "INSUFFICIENT_PERMISSIONS", "message": "This operation requires admin or user role"}}
            )

        return True
