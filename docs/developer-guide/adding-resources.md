# Adding New Resources

This guide walks through creating a new tenant-isolated CRUD resource — from running the scaffold command to wiring it into the application.

---

## The Scaffold Command

The fastest way to add a resource is the `scaffold_resource` management command. It generates all the boilerplate following the Widget pattern.

```bash
# Basic — generates model, service, serializers, views, URLs, tests
python manage.py scaffold_resource Product

# With custom fields
python manage.py scaffold_resource Product \
  --fields price:decimal,active:boolean,quantity:integer

# Skip test generation
python manage.py scaffold_resource Product --no-tests
```

Supported field types: `string`, `text`, `integer`, `decimal`, `boolean`, `date`, `datetime`, `json`.

---

## Generated File Structure

Running `scaffold_resource Product` creates:

```
products/
  __init__.py
  apps.py
  models.py          ← TenantIsolatedModel subclass
  services.py        ← CRUD business logic
  serializers.py     ← Input validation + response formatting
  views.py           ← DRF function-based views with OpenAPI annotations
  urls.py            ← URL patterns
  migrations/
    0001_initial.py  ← Migration with tenant FK and indexes
  tests/
    __init__.py
    test_product_service.py    ← Unit tests
    test_product_properties.py ← Hypothesis property tests
```

Every generated file follows the same structure as the `widgets` app. Read through `widgets/` to understand what each file does before customising.

---

## Step-by-Step: Wiring It In

After the scaffold command completes, three manual steps remain.

### 1. Register the App

Add the new app to `INSTALLED_APPS` in `config/settings.py`:

```python
INSTALLED_APPS = [
    # ...existing apps...
    'products',
]
```

### 2. Register the URLs

Add the URL prefix in `config/urls.py`:

```python
from django.urls import path, include

urlpatterns = [
    # ...existing patterns...
    path('api/products/', include('products.urls')),
]
```

### 3. Run Migrations

```bash
python manage.py migrate
```

Verify the new table exists:

```bash
python manage.py dbshell
\d products   # PostgreSQL
```

---

## Manual Customisation

The scaffold generates a working baseline. Here is where you will typically need to customise.

### Adding Business Rules

Business rules live in the service class (`products/services.py`). The scaffold generates `create_product`, `get_product`, `list_products`, `update_product`, and `delete_product`. Add your logic there:

```python
# products/services.py
from rest_framework.exceptions import ValidationError

class ProductService:

    @staticmethod
    def create_product(tenant_id, user_id, name, price=None, active=None):
        # Custom rule: price must be positive
        if price is not None and price <= 0:
            raise ValidationError({'price': 'Price must be greater than zero.'})

        # Custom rule: enforce a per-tenant product limit
        count = Product.objects.filter(tenant_id=tenant_id).count()
        if count >= 100:
            raise ValidationError({'detail': 'Tenant product limit (100) reached.'})

        return Product.objects.create(
            tenant_id=tenant_id,
            name=name.strip(),
            price=price,
            active=active if active is not None else True,
            created_by_id=user_id,
        )
```

Keep all business logic in the service. Views should only handle HTTP concerns (parsing input, returning responses).

### Adding Relationships

To relate a `Product` to another tenant-scoped model (e.g., `Category`), add a FK that stays within the same tenant:

```python
# products/models.py
class Product(TenantIsolatedModel):
    # ...
    category = models.ForeignKey(
        'categories.Category',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='products',
    )
```

Always verify the FK target belongs to the same tenant before saving:

```python
# products/services.py
@staticmethod
def create_product(tenant_id, user_id, name, category_id=None, ...):
    if category_id:
        try:
            Category.objects.get(id=category_id, tenant_id=tenant_id)
        except Category.DoesNotExist:
            raise ValidationError({'category_id': 'Category not found.'})
    # ...
```

### Adding Custom Filters

Extend `list_products` in the service and add the corresponding query parameter to `ProductFilterSerializer`:

```python
# products/services.py
@staticmethod
def list_products(tenant_id, active_only=False, min_price=None, ...):
    qs = Product.objects.filter(tenant_id=tenant_id).order_by('-created_at')
    if active_only:
        qs = qs.filter(active=True)
    if min_price is not None:
        qs = qs.filter(price__gte=min_price)
    return qs
```

```python
# products/serializers.py
class ProductFilterSerializer(serializers.Serializer):
    active_only = serializers.BooleanField(required=False, default=False)
    min_price = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    # ...existing fields...
```

### Adding Audit Logging

Call `AuditLogger` from the service for security-relevant events:

```python
# products/services.py
from core.audit_logger import AuditLogger

@staticmethod
def delete_product(tenant_id, user_id, product_id):
    product = ProductService.get_product(tenant_id, product_id)
    product.delete()
    AuditLogger.log_event(
        tenant_id=tenant_id,
        event_type='product_deleted',
        user_id=user_id,
        details={'product_id': str(product_id), 'name': product.name},
    )
```

---

## Common Resource Patterns

### Read-Only Resource

For resources that users can only read (not create/update/delete), restrict the view:

```python
# reports/views.py
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def report_list(request):
    tenant_id = get_current_tenant()
    reports = ReportService.list_reports(tenant_id)
    return Response(ReportSerializer(reports, many=True).data)
```

Remove the `POST` handler and the `IsAdminOrUser` check entirely.

### Admin-Only Resource

For resources that only admins can modify:

```python
# config/views.py
@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def tenant_config(request):
    tenant_id = get_current_tenant()

    if request.method == 'GET':
        # All roles can read
        config = ConfigService.get_config(tenant_id)
        return Response(ConfigSerializer(config).data)

    # Only admins can update
    if request.user.role != 'admin':
        return Response(
            {'error': 'Admin role required'},
            status=status.HTTP_403_FORBIDDEN,
        )
    # ...
```

Or use the `IsAdmin` permission class from `authentication.permissions`:

```python
from authentication.permissions import IsAdmin

@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdmin])
def invite_user(request):
    # ...
```

### Nested Resource

For resources that belong to a parent (e.g., `ProductVariant` belongs to `Product`):

```python
# product_variants/services.py
@staticmethod
def create_variant(tenant_id, user_id, product_id, name, sku):
    # Verify parent belongs to tenant
    try:
        product = Product.objects.get(id=product_id, tenant_id=tenant_id)
    except Product.DoesNotExist:
        raise NotFound('Product not found.')

    return ProductVariant.objects.create(
        tenant_id=tenant_id,
        product=product,
        name=name,
        sku=sku,
        created_by_id=user_id,
    )
```

URL pattern for nested resources:

```python
# config/urls.py
path('api/products/<uuid:product_id>/variants/', include('product_variants.urls')),
```

---

## Checklist

Before considering a new resource complete:

- [ ] App added to `INSTALLED_APPS`
- [ ] URLs registered in `config/urls.py`
- [ ] Migration applied (`python manage.py migrate`)
- [ ] Model extends `TenantIsolatedModel` with `tenant` FK
- [ ] Service validates all inputs and raises `ValidationError` / `NotFound`
- [ ] Views check `get_current_tenant()` and return 400 if missing
- [ ] Role checks in place for mutating operations
- [ ] Unit tests cover create, read, list, update, delete, and tenant isolation
- [ ] Property test verifies queries return only the tenant's data
- [ ] OpenAPI annotations added to views (`@extend_schema`)
