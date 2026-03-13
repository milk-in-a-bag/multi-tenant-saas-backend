# Authentication and Authorization

This module provides authentication and role-based access control (RBAC) for the multi-tenant SaaS backend.

## Features

- JWT token-based authentication
- API key authentication
- Role-based access control (RBAC)
- Audit logging for authentication events
- Tenant-isolated user management

## Roles

The system supports three roles with different permission levels:

### Admin Role

- **Permissions**: All operations (read, write, delete, admin)
- **Use cases**: Tenant administrators, system configuration, user management
- **Operations**: Can perform any action within their tenant

### User Role

- **Permissions**: Read and write operations only
- **Use cases**: Regular users who need to create and modify data
- **Operations**: Can read and write data, but cannot delete or perform admin tasks

### Read-Only Role

- **Permissions**: Read operations only
- **Use cases**: Viewers, auditors, reporting users
- **Operations**: Can only view data, cannot modify anything

## Using Authorization in Views

### Method 1: Using RoleBasedPermission (Automatic)

The `RoleBasedPermission` class automatically determines the required operation based on HTTP method:

```python
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from authentication.permissions import RoleBasedPermission

@api_view(['GET'])
@permission_classes([IsAuthenticated, RoleBasedPermission])
def list_widgets(request):
    # Automatically requires 'read' permission
    # Admin, User, and Read-Only roles can access this
    pass

@api_view(['POST'])
@permission_classes([IsAuthenticated, RoleBasedPermission])
def create_widget(request):
    # Automatically requires 'write' permission
    # Only Admin and User roles can access this
    pass

@api_view(['DELETE'])
@permission_classes([IsAuthenticated, RoleBasedPermission])
def delete_widget(request, widget_id):
    # Automatically requires 'delete' permission
    # Only Admin role can access this
    pass
```

### Method 2: Using RoleBasedPermission (Explicit)

You can explicitly specify the required operation:

```python
from rest_framework.views import APIView
from authentication.permissions import RoleBasedPermission

class WidgetDetailView(APIView):
    permission_classes = [IsAuthenticated, RoleBasedPermission]
    required_operation = 'write'  # Explicitly require write permission

    def get(self, request, widget_id):
        # This will require 'write' permission even though it's a GET
        pass
```

### Method 3: Using Convenience Permission Classes

```python
from authentication.permissions import IsAdmin, IsAdminOrUser

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdmin])
def admin_only_endpoint(request):
    # Only admin users can access this
    pass

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminOrUser])
def user_endpoint(request):
    # Admin and User roles can access, but not Read-Only
    pass
```

### Method 4: Manual Authorization Check

For fine-grained control, use the `AuthService.authorize_operation()` method directly:

```python
from authentication.services import AuthService
from rest_framework.exceptions import PermissionDenied

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def custom_endpoint(request):
    # Manual authorization check
    if not AuthService.authorize_operation(request.user.role, 'admin'):
        raise PermissionDenied({
            'error': {
                'code': 'INSUFFICIENT_PERMISSIONS',
                'message': 'This operation requires admin privileges'
            }
        })

    # Proceed with admin-only logic
    pass
```

## Operation Types

The authorization system recognizes four operation types:

- **read**: View data (GET, HEAD, OPTIONS requests)
- **write**: Create or modify data (POST, PUT, PATCH requests)
- **delete**: Remove data (DELETE requests)
- **admin**: Administrative operations (user management, configuration)

## Permission Matrix

| Role      | read | write | delete | admin |
| --------- | ---- | ----- | ------ | ----- |
| admin     | ✓    | ✓     | ✓      | ✓     |
| user      | ✓    | ✓     | ✗      | ✗     |
| read_only | ✓    | ✗     | ✗      | ✗     |

## Error Responses

When a user attempts an unauthorized operation, the API returns:

```json
{
  "error": {
    "code": "INSUFFICIENT_PERMISSIONS",
    "message": "Your role (user) does not permit delete operations"
  }
}
```

HTTP Status: `403 Forbidden`

## Examples

### Example 1: Widget CRUD with Automatic Authorization

```python
from rest_framework.viewsets import ModelViewSet
from authentication.permissions import RoleBasedPermission

class WidgetViewSet(ModelViewSet):
    permission_classes = [IsAuthenticated, RoleBasedPermission]

    # GET /widgets/ - Requires 'read' (all roles)
    # POST /widgets/ - Requires 'write' (admin, user)
    # PUT /widgets/{id}/ - Requires 'write' (admin, user)
    # DELETE /widgets/{id}/ - Requires 'delete' (admin only)
```

### Example 2: Admin-Only User Management

```python
from authentication.permissions import IsAdmin

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdmin])
def create_user(request):
    # Only admins can create users
    pass

@api_view(['PATCH'])
@permission_classes([IsAuthenticated, IsAdmin])
def change_user_role(request, user_id):
    # Only admins can change user roles
    pass
```

### Example 3: Mixed Permissions

```python
from rest_framework.views import APIView
from authentication.permissions import RoleBasedPermission

class ReportView(APIView):
    permission_classes = [IsAuthenticated, RoleBasedPermission]

    def get(self, request):
        # All authenticated users can view reports
        # Automatically requires 'read' permission
        pass

    def post(self, request):
        # Only admin and user roles can generate reports
        # Automatically requires 'write' permission
        pass
```

## Testing Authorization

```python
from authentication.services import AuthService

# Test authorization logic
assert AuthService.authorize_operation('admin', 'read') == True
assert AuthService.authorize_operation('user', 'delete') == False
assert AuthService.authorize_operation('read_only', 'write') == False
```

## Integration with Middleware

The `TenantContextMiddleware` automatically extracts the user's role from JWT tokens or API keys and makes it available via `request.user.role`. The permission classes use this role to enforce authorization.

## Best Practices

1. **Always use IsAuthenticated**: Combine authorization permissions with `IsAuthenticated` to ensure the user is logged in
2. **Use automatic detection**: Let `RoleBasedPermission` automatically detect the operation type based on HTTP method
3. **Be explicit when needed**: Override `required_operation` for non-standard cases
4. **Fail secure**: Invalid or missing roles default to denying all operations
5. **Consistent error messages**: Use the standard error format for authorization failures
6. **Audit logging**: Authentication and authorization events are automatically logged

## See Also

- `authentication/services.py` - Core authorization logic
- `authentication/permissions.py` - DRF permission classes
- `authentication/tests.py` - Authorization test examples
- `core/middleware.py` - Tenant context extraction
