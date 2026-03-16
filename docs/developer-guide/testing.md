# Testing Guide

This guide explains the testing strategy, how to write both unit tests and property-based tests, and how to measure coverage.

---

## Dual Testing Approach

Every feature in this codebase is covered by two complementary test types:

**Unit tests** (`TestCase` subclasses) verify specific behaviours with controlled inputs. They are fast, deterministic, and easy to debug. Use them to cover the happy path, known edge cases, and error conditions.

**Property-based tests** (`hypothesis`) verify that invariants hold across a large space of randomly generated inputs. They are particularly effective at finding edge cases you didn't think to write. Use them to verify tenant isolation, uniqueness constraints, and security boundaries.

Run the full suite:

```bash
pytest
```

Run only unit tests (faster during development):

```bash
pytest -k "not properties"
```

Run only property tests:

```bash
pytest -k "properties"
```

---

## Unit Tests

### Setup Pattern

Every test class that touches the database needs at least one tenant and one user. Use `setUp` to create them:

```python
import uuid
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from tenants.models import Tenant
from authentication.models import User


class ProductServiceTestCase(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            id=str(uuid.uuid4()),
            subscription_tier='free',
            subscription_expiration=timezone.now() + timedelta(days=30),
            status='active',
        )
        self.user = User.objects.create_user(
            tenant=self.tenant,
            username='testuser',
            email='test@example.com',
            password='testpass123',
            role='admin',
        )
```

### Mocking Tenant Context

Service methods receive `tenant_id` as a parameter, so most unit tests do not need to mock the middleware. However, if the code under test calls `get_current_tenant()` internally, patch it:

```python
from unittest.mock import patch

def test_create_product(self):
    with patch('core.middleware.get_current_tenant', return_value=self.tenant.id):
        product = ProductService.create_product(
            tenant_id=self.tenant.id,
            user_id=self.user.id,
            name='Test Product',
        )
    self.assertEqual(product.name, 'Test Product')
    self.assertEqual(str(product.tenant_id), str(self.tenant.id))
```

Alternatively, use `set_current_tenant` / `clear_current_tenant` directly:

```python
from core.middleware import set_current_tenant, clear_current_tenant

def setUp(self):
    # ...
    set_current_tenant(str(self.tenant.id))

def tearDown(self):
    clear_current_tenant()
```

### Testing Tenant Isolation

Always create a second tenant and verify its data is not visible to the first:

```python
def test_tenant_isolation(self):
    other_tenant = Tenant.objects.create(
        id=str(uuid.uuid4()),
        subscription_tier='free',
        subscription_expiration=timezone.now() + timedelta(days=30),
        status='active',
    )
    other_user = User.objects.create_user(
        tenant=other_tenant,
        username='otheruser',
        email='other@example.com',
        password='testpass123',
        role='admin',
    )

    # Create a product for the other tenant
    other_product = ProductService.create_product(
        tenant_id=other_tenant.id,
        user_id=other_user.id,
        name='Other Tenant Product',
    )

    # Querying as self.tenant must not return the other tenant's product
    from rest_framework.exceptions import NotFound
    with self.assertRaises(NotFound):
        ProductService.get_product(self.tenant.id, other_product.id)

    # List must also be empty
    results = ProductService.list_products(self.tenant.id)
    self.assertEqual(results.count(), 0)
```

### Testing Authorization Boundaries

```python
def test_read_only_user_cannot_create(self):
    from rest_framework.test import APIClient
    from authentication.services import AuthService

    read_only_user = User.objects.create_user(
        tenant=self.tenant,
        username='readonly',
        email='readonly@example.com',
        password='testpass123',
        role='read_only',
    )
    auth = AuthService.authenticate_user(
        tenant_id=str(self.tenant.id),
        username='readonly',
        password='testpass123',
    )
    token = auth['access_token']

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    response = client.post('/api/products/', {'name': 'New Product'})

    self.assertEqual(response.status_code, 403)

def test_admin_can_delete(self):
    from rest_framework.test import APIClient
    from authentication.services import AuthService

    product = ProductService.create_product(self.tenant.id, self.user.id, 'To Delete')
    auth = AuthService.authenticate_user(
        tenant_id=str(self.tenant.id),
        username='testuser',
        password='testpass123',
    )
    token = auth['access_token']

    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    response = client.delete(f'/api/products/{product.id}/')

    self.assertEqual(response.status_code, 204)
```

### Testing Rate Limiting

```python
from core.models import RateLimit
from django.utils import timezone

def test_rate_limit_exceeded_returns_429(self):
    from rest_framework.test import APIClient
    from authentication.services import AuthService

    # Set the tenant's request count to the free tier limit
    RateLimit.objects.create(
        tenant_id=self.tenant.id,
        request_count=100,  # free tier limit
        window_start=timezone.now().replace(minute=0, second=0, microsecond=0),
    )

    auth = AuthService.authenticate_user(
        tenant_id=str(self.tenant.id),
        username='testuser',
        password='testpass123',
    )
    token = auth['access_token']
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    response = client.get('/api/products/')
    self.assertEqual(response.status_code, 429)
    self.assertIn('Retry-After', response)
```

---

## Property-Based Tests with Hypothesis

### Setup

Property tests use `hypothesis.extra.django.TestCase` instead of `django.test.TestCase`. This ensures the database is properly reset between Hypothesis examples.

```python
import uuid
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase
from core.middleware import set_current_tenant, clear_current_tenant


class ProductPropertyTests(TestCase):

    def setUp(self):
        clear_current_tenant()

    def tearDown(self):
        clear_current_tenant()
```

### Tenant Isolation Property

The most important property to test: queries for one tenant must never return another tenant's data.

```python
@given(st.text(min_size=1, max_size=200).filter(lambda s: s.strip()))
@settings(max_examples=20, deadline=5000)
def test_queries_return_only_tenant_data(self, name):
    from tenants.models import Tenant
    from authentication.models import User
    from django.utils import timezone
    from datetime import timedelta

    # Create a second tenant with a product
    other_tenant = Tenant.objects.create(
        id=str(uuid.uuid4()),
        subscription_tier='free',
        subscription_expiration=timezone.now() + timedelta(days=30),
        status='active',
    )
    other_user = User.objects.create_user(
        tenant=other_tenant,
        username=f'other_{uuid.uuid4().hex[:8]}',
        email=f'other_{uuid.uuid4().hex[:8]}@example.com',
        password='testpass123',
        role='admin',
    )
    unique_name = f'{name}_{uuid.uuid4().hex[:8]}'
    ProductService.create_product(other_tenant.id, other_user.id, unique_name)

    # Query as self.tenant — must see nothing from other_tenant
    results = ProductService.list_products(self.tenant.id)
    tenant_ids = {str(r.tenant_id) for r in results}
    self.assertNotIn(str(other_tenant.id), tenant_ids)
```

### Name Uniqueness Property

```python
@given(st.text(min_size=1, max_size=200).filter(lambda s: s.strip()))
@settings(max_examples=20, deadline=5000)
def test_name_uniqueness_within_tenant(self, name):
    from rest_framework.exceptions import ValidationError

    unique_name = f'{name}_{uuid.uuid4().hex[:8]}'
    ProductService.create_product(self.tenant.id, self.user.id, unique_name)

    with self.assertRaises(ValidationError):
        ProductService.create_product(self.tenant.id, self.user.id, unique_name)
```

### Same Name Allowed Across Tenants

```python
@given(st.text(min_size=1, max_size=200).filter(lambda s: s.strip()))
@settings(max_examples=20, deadline=5000)
def test_same_name_allowed_in_different_tenants(self, name):
    from tenants.models import Tenant
    from authentication.models import User
    from django.utils import timezone
    from datetime import timedelta

    other_tenant = Tenant.objects.create(
        id=str(uuid.uuid4()),
        subscription_tier='free',
        subscription_expiration=timezone.now() + timedelta(days=30),
        status='active',
    )
    other_user = User.objects.create_user(
        tenant=other_tenant,
        username=f'other_{uuid.uuid4().hex[:8]}',
        email=f'other_{uuid.uuid4().hex[:8]}@example.com',
        password='testpass123',
        role='admin',
    )
    unique_name = f'{name}_{uuid.uuid4().hex[:8]}'

    # Both tenants can have a product with the same name
    p1 = ProductService.create_product(self.tenant.id, self.user.id, unique_name)
    p2 = ProductService.create_product(other_tenant.id, other_user.id, unique_name)

    self.assertEqual(p1.name, p2.name)
    self.assertNotEqual(str(p1.tenant_id), str(p2.tenant_id))
```

### Hypothesis Settings

| Setting        | Recommended value | Notes                                          |
| -------------- | ----------------- | ---------------------------------------------- |
| `max_examples` | 20                | Enough to catch most issues without slowing CI |
| `deadline`     | 5000 (ms)         | DB operations are slower than pure Python      |

For CI environments where you want more thorough checking:

```python
import os
MAX_EXAMPLES = int(os.environ.get('HYPOTHESIS_MAX_EXAMPLES', '20'))

@settings(max_examples=MAX_EXAMPLES, deadline=None)
```

---

## Example Tests for Common Scenarios

### Validation Rejects Invalid Input

```python
def test_empty_name_raises_validation_error(self):
    from rest_framework.exceptions import ValidationError
    with self.assertRaises(ValidationError) as ctx:
        ProductService.create_product(self.tenant.id, self.user.id, name='   ')
    self.assertIn('name', ctx.exception.detail)

def test_negative_price_raises_validation_error(self):
    from rest_framework.exceptions import ValidationError
    with self.assertRaises(ValidationError):
        ProductService.create_product(
            self.tenant.id, self.user.id, name='Bad Product', price=-1
        )
```

### Cross-Tenant Update Rejected

```python
def test_cannot_update_other_tenants_product(self):
    from rest_framework.exceptions import NotFound
    from tenants.models import Tenant
    from authentication.models import User
    from django.utils import timezone
    from datetime import timedelta

    other_tenant = Tenant.objects.create(
        id=str(uuid.uuid4()),
        subscription_tier='free',
        subscription_expiration=timezone.now() + timedelta(days=30),
        status='active',
    )
    other_user = User.objects.create_user(
        tenant=other_tenant, username='other', email='o@o.com',
        password='pass', role='admin',
    )
    product = ProductService.create_product(other_tenant.id, other_user.id, 'Other Product')

    with self.assertRaises(NotFound):
        ProductService.update_product(self.tenant.id, product.id, name='Hijacked')
```

---

## Running Tests

```bash
# Full suite
pytest

# With verbose output
pytest -v

# Single file
pytest products/tests/test_product_service.py

# Single test
pytest products/tests/test_product_service.py::ProductServiceTestCase::test_tenant_isolation

# Stop on first failure
pytest -x
```

---

## Coverage

Measure coverage with `pytest-cov`:

```bash
pytest --cov=. --cov-report=term-missing
```

Generate an HTML report:

```bash
pytest --cov=. --cov-report=html
open htmlcov/index.html
```

Coverage goals:

| Area            | Target |
| --------------- | ------ |
| Service classes | 90%+   |
| View functions  | 80%+   |
| Serializers     | 80%+   |
| Middleware      | 80%+   |
| Overall         | 80%+   |

Lines that are intentionally excluded (e.g., `pragma: no cover`) should be rare and justified. Focus coverage efforts on service and middleware code — that is where tenant isolation and security logic lives.
