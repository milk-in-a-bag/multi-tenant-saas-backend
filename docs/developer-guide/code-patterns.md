# Code Patterns

Standard patterns used throughout this codebase. Follow these when adding new features to stay consistent with the existing implementation.

---

## 1. Tenant-Isolated Database Queries

All tenant-scoped models extend `TenantIsolatedModel` and use `TenantManager` as their default manager. When a tenant context is set (by `TenantContextMiddleware`), every `objects` query is automatically filtered to that tenant.

### List

```python
# No WHERE clause needed — TenantManager injects it
products = Product.objects.filter(active=True).order_by('-created_at')
```

### Get a Single Record

```python
from rest_framework.exceptions import NotFound

try:
    product = Product.objects.get(id=product_id, tenant_id=tenant_id)
except Product.DoesNotExist:
    raise NotFound('Product not found.')
```

Passing `tenant_id` explicitly in `.get()` is a safety net for code paths where the thread-local context may not be set (e.g., background tasks).

### Create

```python
from django.db import IntegrityError
from rest_framework.exceptions import ValidationError

try:
    product = Product.objects.create(
        tenant_id=tenant_id,
        name=name.strip(),
        price=price,
        created_by_id=user_id,
    )
except IntegrityError:
    raise ValidationError({'name': f"A product named '{name}' already exists."})
```

### Update

```python
product = Product.objects.get(id=product_id, tenant_id=tenant_id)
product.name = new_name
try:
    product.save()
except IntegrityError:
    raise ValidationError({'name': 'Name already in use.'})
```

### Delete

```python
product = Product.objects.get(id=product_id, tenant_id=tenant_id)
product.delete()
```

### Bulk Operations

Bulk operations bypass model-level validation. Always include an explicit `tenant_id` filter:

```python
# Safe
Product.objects.filter(tenant_id=tenant_id, active=False).delete()

# UNSAFE — never do this
Product.objects.filter(active=False).delete()
```

### Raw SQL

Use `DataIsolator` for raw queries that need tenant filtering:

```python
from core.data_isolator import DataIsolator

results = DataIsolator.query(
    "SELECT * FROM products WHERE {tenant_filter} AND price > %s",
    params=[min_price],
)
```

**Pitfalls to avoid:**

- Never use `all_objects` in request handlers — it bypasses tenant filtering.
- Never create FK references across tenants.
- Always call `clear_current_tenant()` in `tearDown` when writing tests.

---

## 2. Authorization Checks

### In Views — Role Check

The simplest pattern is an inline role check in the view function:

```python
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_product(request):
    if request.user.role not in ('admin', 'user'):
        return Response(
            {'error': 'Admin or user role required'},
            status=status.HTTP_403_FORBIDDEN,
        )
    # ...
```

### Using Permission Classes

For reusable role enforcement, use the permission classes from `authentication.permissions`:

```python
from authentication.permissions import IsAdmin, IsAdminOrUser

# Admin only
@api_view(['DELETE'])
@permission_classes([IsAuthenticated, IsAdmin])
def delete_tenant(request):
    # ...

# Admin or user (excludes read_only)
@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminOrUser])
def create_product(request):
    # ...
```

### In Services — Programmatic Check

When authorization logic belongs in the service layer:

```python
from authentication.services import AuthService
from rest_framework.exceptions import PermissionDenied

class ProductService:
    @staticmethod
    def delete_product(tenant_id, requesting_user, product_id):
        if not AuthService.authorize_operation(requesting_user.role, 'delete'):
            raise PermissionDenied('Delete operation requires admin or user role.')
        # ...
```

### Role Hierarchy

| Role        | read | write | delete | admin |
| ----------- | ---- | ----- | ------ | ----- |
| `admin`     | ✓    | ✓     | ✓      | ✓     |
| `user`      | ✓    | ✓     | ✓      | ✗     |
| `read_only` | ✓    | ✗     | ✗      | ✗     |

**Pitfalls to avoid:**

- Never trust `request.user.role` without also verifying `request.user.is_authenticated`.
- Always apply `@permission_classes([IsAuthenticated])` — never rely on role checks alone.
- Fail closed: if a role is unrecognised, deny access.

---

## 3. Input Validation

Use DRF `Serializer` classes for all input validation. Keep them in `serializers.py` and keep views thin.

### Create Serializer

```python
# products/serializers.py
from rest_framework import serializers

class ProductCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    description = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError('Name cannot be blank.')
        return value.strip()

    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError('Price must be greater than zero.')
        return value
```

### Update Serializer (all fields optional)

```python
class ProductUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError('Name cannot be blank.')
        return value.strip()
```

### Query Parameter Serializer

```python
class ProductFilterSerializer(serializers.Serializer):
    active_only = serializers.BooleanField(required=False, default=False)
    min_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
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
```

### Using Serializers in Views

```python
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def product_list(request):
    if request.method == 'POST':
        serializer = ProductCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        product = ProductService.create_product(
            tenant_id=get_current_tenant(),
            user_id=request.user.id,
            name=data['name'],
            price=data['price'],
        )
        return Response(ProductSerializer(product).data, status=status.HTTP_201_CREATED)
```

**Pitfalls to avoid:**

- Never access `request.data` directly without validating through a serializer first.
- Always use `serializer.validated_data`, not `serializer.data`, when passing values to services.
- Use separate create and update serializers — update fields are typically optional.

---

## 4. Error Handling and Responses

All errors are formatted by the custom exception handler in `api/exception_handler.py`. Raise standard DRF exceptions from services and views — the handler converts them to the consistent shape:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input.",
    "details": { "name": ["This field is required."] }
  }
}
```

### Standard Exceptions to Use

```python
from rest_framework.exceptions import ValidationError, NotFound, PermissionDenied

# Input validation failure
raise ValidationError({'price': 'Price must be greater than zero.'})

# Resource not found (also used for cross-tenant access — same response)
raise NotFound('Product not found.')

# Insufficient permissions
raise PermissionDenied('Admin role required.')
```

### Returning Errors Directly in Views

For cases where you need to return an error without raising an exception:

```python
from rest_framework.response import Response
from rest_framework import status

# Missing tenant context
tenant_id = get_current_tenant()
if not tenant_id:
    return Response(
        {'error': 'Tenant context required'},
        status=status.HTTP_400_BAD_REQUEST,
    )

# Role check failure
if request.user.role not in ('admin', 'user'):
    return Response(
        {'error': 'Admin or user role required'},
        status=status.HTTP_403_FORBIDDEN,
    )
```

### Never Reveal Cross-Tenant Information

When a resource is not found — whether it genuinely doesn't exist or belongs to another tenant — always raise `NotFound`. Never return a 403 that would confirm the resource exists:

```python
# CORRECT — same response whether missing or cross-tenant
try:
    product = Product.objects.get(id=product_id, tenant_id=tenant_id)
except Product.DoesNotExist:
    raise NotFound('Product not found.')

# WRONG — reveals that the product exists in another tenant
product = Product.all_objects.get(id=product_id)
if product.tenant_id != tenant_id:
    raise PermissionDenied('Access denied.')
```

**Pitfalls to avoid:**

- Never catch `Exception` broadly and swallow errors silently.
- Never include stack traces or internal details in error responses.
- Always use `NotFound` (not `PermissionDenied`) for cross-tenant access attempts.

---

## 5. Audit Logging

Use `AuditLogger` from `core.audit_logger` for security-relevant events. Call it from the service layer, after the operation succeeds.

### Logging a Custom Event

```python
from core.audit_logger import AuditLogger

class ProductService:
    @staticmethod
    def delete_product(tenant_id, user_id, product_id):
        product = ProductService.get_product(tenant_id, product_id)
        product_name = product.name
        product.delete()

        # Log after successful deletion
        AuditLogger.log_event(
            tenant_id=tenant_id,
            event_type='product_deleted',
            user_id=user_id,
            details={
                'product_id': str(product_id),
                'product_name': product_name,
            },
        )
```

### Built-In Log Methods

`AuditLogger` provides helpers for common events — prefer these over `log_event` directly:

```python
AuditLogger.log_authentication_success(tenant_id, user_id, username, ip_address)
AuditLogger.log_authentication_failure(tenant_id, username, reason, ip_address)
AuditLogger.log_role_change(tenant_id, target_user_id, old_role, new_role, admin_user_id)
AuditLogger.log_api_key_created(tenant_id, key_id, user_id, created_by)
AuditLogger.log_api_key_revoked(tenant_id, key_id, revoked_by)
AuditLogger.log_subscription_change(tenant_id, old_tier, new_tier, old_exp, new_exp)
AuditLogger.log_tenant_deletion(tenant_id, admin_user_id)
```

### What to Log

Log events that are security-relevant or useful for compliance:

- Authentication successes and failures
- Role changes
- API key creation and revocation
- Sensitive data deletion
- Subscription changes
- Admin-only operations

Do not log routine read operations — audit logs are for security events, not access logs.

### Audit Log Isolation

`AuditLogger` uses `AuditLog.all_objects` (the unfiltered manager) to write logs. This is intentional — logs must be written even when the tenant context is being cleared. Reads go through the filtered manager, so tenants can only query their own logs.

**Pitfalls to avoid:**

- Never log passwords, tokens, or API key values — only IDs and hashes.
- Log after the operation succeeds, not before (avoids logging events that didn't happen).
- Always include `tenant_id` — logs without it cannot be queried by the tenant.

---

## 6. API Endpoints with Middleware Ordering

### Middleware Stack

Requests pass through middleware in this order (configured in `config/settings.py`):

```
1. TenantContextMiddleware   — extracts tenant_id from JWT/API key → thread-local
2. RateLimitMiddleware       — checks per-tenant request quota
3. Django auth middleware    — populates request.user
4. View function             — handles business logic
```

This ordering matters: rate limiting runs after tenant context is set (it needs `tenant_id`), and views run after authentication (they need `request.user`).

### Standard View Structure

```python
# products/views.py
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from core.middleware import get_current_tenant

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def product_list(request):
    # 1. Get tenant context (set by TenantContextMiddleware)
    tenant_id = get_current_tenant()
    if not tenant_id:
        return Response({'error': 'Tenant context required'}, status=400)

    if request.method == 'GET':
        # 2. Validate query parameters
        filter_ser = ProductFilterSerializer(data=request.query_params)
        if not filter_ser.is_valid():
            return Response(filter_ser.errors, status=400)

        # 3. Call service (handles business logic and DB access)
        params = filter_ser.validated_data
        qs = ProductService.list_products(tenant_id, **params)

        # 4. Paginate and serialize
        page_data = _paginate(qs, params['page'], params['page_size'])
        page_data['results'] = ProductSerializer(page_data['results'], many=True).data
        return Response(page_data, status=200)

    # POST — check role before processing
    if request.user.role not in ('admin', 'user'):
        return Response({'error': 'Admin or user role required'}, status=403)

    serializer = ProductCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=400)

    product = ProductService.create_product(
        tenant_id=tenant_id,
        user_id=request.user.id,
        **serializer.validated_data,
    )
    return Response(ProductSerializer(product).data, status=201)
```

### OpenAPI Annotations

Add `@extend_schema` decorators to every view for automatic API documentation:

```python
from drf_spectacular.utils import extend_schema, OpenApiResponse

@extend_schema(
    tags=['products'],
    summary='Create product',
    description='Create a new product for the authenticated tenant. Requires admin or user role.',
    request=ProductCreateSerializer,
    responses={
        201: OpenApiResponse(response=ProductSerializer, description='Product created'),
        400: OpenApiResponse(description='Validation error'),
        401: OpenApiResponse(description='Not authenticated'),
        403: OpenApiResponse(description='Insufficient role'),
        429: OpenApiResponse(description='Rate limit exceeded'),
    },
    methods=['POST'],
)
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_product(request):
    # ...
```

### Pagination Helper

Copy the `_paginate` helper from `widgets/views.py` into your views module:

```python
def _paginate(queryset, page, page_size):
    total = queryset.count()
    offset = (page - 1) * page_size
    items = queryset[offset: offset + page_size]
    return {'count': total, 'page': page, 'page_size': page_size, 'results': items}
```

**Pitfalls to avoid:**

- Never skip the `get_current_tenant()` check — views can be called in contexts where middleware didn't run (e.g., tests).
- Always apply `@permission_classes([IsAuthenticated])` — never rely on role checks alone.
- Keep views thin: parse input, call service, return response. No business logic in views.
