# Tenant Isolation Guide

This guide explains how tenant data isolation works in this system, how to build new tenant-isolated models, and how to test that isolation correctly.

---

## How It Works

The system uses a **shared-database, shared-schema** multi-tenancy model. Every tenant's data lives in the same tables, distinguished by a `tenant_id` foreign key column. The `DataIsolator` subsystem ensures that queries automatically filter to the current tenant's data — no manual `WHERE tenant_id = ?` clauses needed in application code.

### The Three-Layer Stack

```
HTTP Request
    │
    ▼
TenantContextMiddleware          ← extracts tenant_id from JWT / API key
    │                               stores it in thread-local storage
    ▼
TenantManager.get_queryset()     ← injects WHERE tenant_id = <current>
    │                               on every ORM query
    ▼
TenantIsolatedModel.save/delete  ← validates tenant_id on writes,
                                    blocks cross-tenant mutations
```

### Thread-Local Tenant Context

`TenantContextMiddleware` (in `core/middleware.py`) runs on every request. It reads the `tenant_id` claim from the JWT token or looks it up from the API key hash, then stores it in thread-local storage:

```python
# core/middleware.py
_thread_locals = threading.local()

def set_current_tenant(tenant_id):
    _thread_locals.tenant_id = tenant_id

def get_current_tenant():
    return getattr(_thread_locals, 'tenant_id', None)
```

Thread-local storage means each concurrent request has its own isolated `tenant_id` — there is no risk of one request's tenant context leaking into another.

The middleware clears the context in `process_response` and `process_exception`, so it never persists across requests.

### Automatic Query Filtering

`TenantManager` (in `core/data_isolator.py`) overrides `get_queryset()` to append a `tenant_id` filter whenever a tenant context is set:

```python
class TenantManager(models.Manager):
    def get_queryset(self):
        queryset = super().get_queryset()
        tenant_id = get_current_tenant()
        if tenant_id:
            queryset = queryset.filter(tenant_id=tenant_id)
        return queryset
```

Any model that uses `TenantManager` as its default manager gets this filtering for free. `Widget.objects.all()` in a request context for tenant `acme-corp` is equivalent to `Widget.objects.filter(tenant_id='acme-corp')`.

### Write Protection

`TenantIsolatedModel.save()` and `.delete()` both validate that the object's `tenant_id` matches the current context before proceeding. Attempting to save or delete an object belonging to a different tenant raises `TenantIsolationError`.

---

## Creating a Tenant-Isolated Model

Extend `TenantIsolatedModel` and add a `tenant` ForeignKey. The `Widget` model is the canonical example:

```python
# myapp/models.py
import uuid
from django.db import models
from core.data_isolator import TenantIsolatedModel


class Product(TenantIsolatedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='products',
        db_column='tenant_id',
    )
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'products'
        unique_together = [('tenant', 'name')]
        indexes = [
            models.Index(fields=['tenant'], name='idx_products_tenant'),
        ]
```

Key points:

- Inherit from `TenantIsolatedModel`, not `models.Model`.
- Always name the FK field `tenant` with `db_column='tenant_id'`.
- Add a `unique_together` constraint on `('tenant', 'name')` if names should be unique per tenant.
- Index the `tenant` column — queries always filter by it.

Then generate and run the migration:

```bash
python manage.py makemigrations myapp
python manage.py migrate
```

---

## Tenant-Isolated Query Examples

All examples below assume `TenantContextMiddleware` has already set the tenant context (i.e., you are inside a request handler or have called `set_current_tenant()` manually in a test).

### List

```python
# Returns only the current tenant's products — no filter needed
products = Product.objects.all()

# Additional filters compose naturally
active_products = Product.objects.filter(price__gt=0).order_by('name')
```

### Get a Single Record

```python
from rest_framework.exceptions import NotFound

try:
    product = Product.objects.get(id=product_id)
except Product.DoesNotExist:
    raise NotFound('Product not found.')
```

If `product_id` belongs to a different tenant, `DoesNotExist` is raised — the same as if the record did not exist. This prevents information leakage about other tenants' data.

### Create

```python
# tenant_id is injected automatically by TenantManager.create()
product = Product.objects.create(
    name='Widget Pro',
    price='49.99',
    created_by_id=request.user.id,
)
```

You can also pass `tenant_id` explicitly — useful in service methods that receive it as a parameter:

```python
product = Product.objects.create(
    tenant_id=tenant_id,
    name='Widget Pro',
    price='49.99',
    created_by_id=user_id,
)
```

### Update

```python
product = Product.objects.get(id=product_id)
product.name = 'Widget Pro Max'
product.save()  # TenantIsolatedModel.save() validates tenant_id before writing
```

### Delete

```python
product = Product.objects.get(id=product_id)
product.delete()  # TenantIsolatedModel.delete() validates tenant_id before deleting
```

### Bulk Operations

Bulk operations bypass `TenantIsolatedModel.save()` and `.delete()`. Use them carefully and always include an explicit `tenant_id` filter:

```python
# Safe — explicit tenant filter
Product.objects.filter(tenant_id=tenant_id, price=0).delete()

# UNSAFE — do not do this
Product.objects.filter(price=0).delete()  # deletes across ALL tenants
```

---

## Testing Tenant Isolation

### Unit Tests — Mocking Tenant Context

Use `set_current_tenant` and `clear_current_tenant` from `core.middleware` to control the tenant context in tests:

```python
import pytest
from django.test import TestCase
from core.middleware import set_current_tenant, clear_current_tenant
from tenants.models import Tenant
from myapp.models import Product


class TestProductIsolation(TestCase):
    def setUp(self):
        clear_current_tenant()
        self.tenant_a = Tenant.objects.create(
            id='tenant-a',
            subscription_tier='free',
            subscription_expiration='2099-01-01T00:00:00Z',
            status='active',
        )
        self.tenant_b = Tenant.objects.create(
            id='tenant-b',
            subscription_tier='free',
            subscription_expiration='2099-01-01T00:00:00Z',
            status='active',
        )

    def tearDown(self):
        clear_current_tenant()

    def test_tenant_a_cannot_see_tenant_b_products(self):
        # Create a product for tenant B
        set_current_tenant('tenant-b')
        Product.objects.create(name='B Product', price='10.00', tenant_id='tenant-b')

        # Switch to tenant A — should see nothing
        set_current_tenant('tenant-a')
        products = Product.objects.all()
        self.assertEqual(products.count(), 0)

    def test_create_sets_tenant_id_automatically(self):
        set_current_tenant('tenant-a')
        product = Product.objects.create(name='A Product', price='5.00', tenant_id='tenant-a')
        self.assertEqual(product.tenant_id, 'tenant-a')

    def test_cross_tenant_save_raises_error(self):
        from core.data_isolator import TenantIsolationError

        # Create product as tenant A
        set_current_tenant('tenant-a')
        product = Product.objects.create(name='A Product', price='5.00', tenant_id='tenant-a')

        # Switch to tenant B and try to modify it
        set_current_tenant('tenant-b')
        product.name = 'Hijacked'
        with self.assertRaises(TenantIsolationError):
            product.save()
```

### Property-Based Tests with Hypothesis

Property tests verify isolation holds across many randomly generated tenant configurations. See `core/tests/test_data_isolation_properties.py` for the full reference implementation. The pattern is:

```python
import pytest
from hypothesis import given, strategies as st, settings
from hypothesis.extra.django import TestCase
from core.middleware import set_current_tenant, clear_current_tenant
from tenants.models import Tenant
from myapp.models import Product


@pytest.mark.django_db
class TestProductIsolationProperties(TestCase):
    def setUp(self):
        clear_current_tenant()

    def tearDown(self):
        clear_current_tenant()

    @settings(max_examples=20, deadline=None)
    @given(
        tenant_ids=st.lists(
            st.from_regex(r'tenant-[a-z]{4,8}', fullmatch=True),
            min_size=2,
            max_size=5,
            unique=True,
        ),
        querying_index=st.integers(min_value=0, max_value=100),
    )
    def test_queries_return_only_tenant_data(self, tenant_ids, querying_index):
        """
        **Validates: Requirements 3.1, 3.3**

        For any set of tenants, querying as one tenant must never return
        records belonging to another tenant.
        """
        # Create tenants and seed one product each
        for tid in tenant_ids:
            tenant = Tenant.objects.create(
                id=tid,
                subscription_tier='free',
                subscription_expiration='2099-01-01T00:00:00Z',
                status='active',
            )
            set_current_tenant(tid)
            Product.objects.create(name=f'product-{tid}', price='1.00', tenant_id=tid)

        # Query as one of the tenants
        querying_tenant = tenant_ids[querying_index % len(tenant_ids)]
        set_current_tenant(querying_tenant)

        results = list(Product.objects.all())

        # Every result must belong to the querying tenant
        for product in results:
            assert product.tenant_id == querying_tenant

        # No results from other tenants
        other_ids = set(tenant_ids) - {querying_tenant}
        result_tenant_ids = {p.tenant_id for p in results}
        assert not result_tenant_ids.intersection(other_ids)
```

---

## Common Pitfalls

### 1. Using Django's Default Manager

`TenantIsolatedModel` provides two managers:

| Manager       | Behaviour                                                   |
| ------------- | ----------------------------------------------------------- |
| `objects`     | Tenant-filtered — use this in application code              |
| `all_objects` | Unfiltered — use only in admin, migrations, or system tasks |

```python
# CORRECT — filtered to current tenant
Widget.objects.all()

# WRONG in application code — bypasses isolation
Widget.all_objects.all()
```

Only use `all_objects` in management commands, data migrations, or admin views where you intentionally need cross-tenant access.

### 2. Calling `.objects.all()` Without Tenant Context

If no tenant context is set (e.g., in a management command or background task), `TenantManager` returns an unfiltered queryset. This is intentional for system-level operations, but dangerous if you forget to set the context in a request handler.

```python
# In a management command — context is not set, returns ALL records
Widget.objects.all()  # returns widgets for every tenant

# Always set context explicitly in background tasks
from core.middleware import set_current_tenant
set_current_tenant(tenant_id)
widgets = Widget.objects.all()  # now filtered
```

### 3. Bypassing the ORM with Raw SQL

Raw SQL queries do not go through `TenantManager`. You must add the `tenant_id` filter manually, or use `DataIsolator.query()` which handles it for you:

```python
# WRONG — no tenant filter
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute("SELECT * FROM widgets")

# CORRECT — use DataIsolator for raw queries
from core.data_isolator import DataIsolator
results = DataIsolator.query(
    "SELECT * FROM widgets WHERE {tenant_filter} AND name = %s",
    params=['My Widget'],
)

# ALSO CORRECT — add the filter yourself
with connection.cursor() as cursor:
    cursor.execute(
        "SELECT * FROM widgets WHERE tenant_id = %s AND name = %s",
        [tenant_id, 'My Widget'],
    )
```

### 4. Cross-Tenant Foreign Key References

Never create a FK from one tenant's record to another tenant's record. All FK relationships must stay within the same tenant:

```python
# WRONG — Order references a Product from a different tenant
order = Order.objects.create(
    tenant_id='tenant-a',
    product_id=some_product_from_tenant_b,  # cross-tenant FK!
)

# CORRECT — always verify the FK target belongs to the same tenant
product = Product.objects.get(id=product_id)  # TenantManager filters this
order = Order.objects.create(
    tenant_id=tenant_id,
    product=product,
)
```

### 5. Bulk Operations Bypass Model-Level Validation

`QuerySet.update()` and `QuerySet.delete()` skip `TenantIsolatedModel.save()` and `.delete()`. Always include an explicit `tenant_id` filter:

```python
# WRONG — could affect other tenants if context is missing
Widget.objects.filter(name='old').update(name='new')

# CORRECT — explicit tenant scope
Widget.objects.filter(tenant_id=tenant_id, name='old').update(name='new')
```

### 6. Not Testing with Multiple Tenants

A test that only creates one tenant cannot verify isolation. Always create at least two tenants and assert that querying as one does not return the other's data:

```python
# WEAK — only one tenant, can't detect isolation failures
def test_list_widgets(self):
    set_current_tenant('tenant-a')
    Widget.objects.create(name='W1', tenant_id='tenant-a', ...)
    self.assertEqual(Widget.objects.count(), 1)  # passes even without isolation

# STRONG — two tenants, verifies isolation
def test_list_widgets_isolated(self):
    # Seed tenant B's data
    set_current_tenant('tenant-b')
    Widget.objects.create(name='W-B', tenant_id='tenant-b', ...)

    # Query as tenant A — must see nothing
    set_current_tenant('tenant-a')
    self.assertEqual(Widget.objects.count(), 0)
```

---

## Reference

| Component                 | File                                           | Purpose                                                        |
| ------------------------- | ---------------------------------------------- | -------------------------------------------------------------- |
| `TenantContextMiddleware` | `core/middleware.py`                           | Extracts `tenant_id` from JWT/API key, stores in thread-local  |
| `get_current_tenant()`    | `core/middleware.py`                           | Read current tenant from thread-local                          |
| `set_current_tenant()`    | `core/middleware.py`                           | Set tenant context (use in tests and background tasks)         |
| `clear_current_tenant()`  | `core/middleware.py`                           | Clear tenant context (call in `tearDown`)                      |
| `TenantManager`           | `core/data_isolator.py`                        | Django manager that auto-filters by `tenant_id`                |
| `TenantIsolatedModel`     | `core/data_isolator.py`                        | Abstract base model — extend this for all tenant-scoped models |
| `DataIsolator`            | `core/data_isolator.py`                        | Utilities for raw SQL with tenant filtering                    |
| `TenantIsolationError`    | `core/data_isolator.py`                        | Raised on cross-tenant write attempts                          |
| `Widget`                  | `widgets/models.py`                            | Canonical example of a tenant-isolated model                   |
| Property tests            | `core/tests/test_data_isolation_properties.py` | Reference Hypothesis tests for isolation properties            |
