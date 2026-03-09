# Core Module - Data Isolation Layer

This module provides the core infrastructure for tenant data isolation in the multi-tenant SaaS backend.

## Components

### TenantContextMiddleware

Middleware that extracts tenant context from JWT tokens or API keys and stores it in thread-local storage.

**Features:**

- Extracts tenant_id from JWT token claims
- Extracts tenant_id from API key lookups
- Stores tenant context in thread-local storage
- Automatically clears context after request completion
- Skips tenant extraction for public endpoints (health checks, API docs)

**Usage:**
The middleware is automatically applied to all requests. No manual configuration needed.

### DataIsolator

Core class that enforces tenant data isolation at the database layer.

**Methods:**

- `validate_tenant_context()`: Validates that tenant context is present, raises TenantIsolationError if missing
- `query(sql, params)`: Execute raw SQL query with automatic tenant filtering
- `write(sql, params)`: Execute raw SQL write with automatic tenant association
- `delete_tenant_data(tenant_id)`: Delete all data for a specific tenant

**Example:**

```python
from core import DataIsolator

# Query with automatic tenant filtering
results = DataIsolator.query(
    "SELECT * FROM widgets WHERE {tenant_filter}",
    []
)

# Write with automatic tenant association
DataIsolator.write(
    "INSERT INTO widgets (tenant_id, name) VALUES (%s, %s)",
    [tenant_id, "My Widget"]
)
```

### TenantManager

Custom Django model manager that automatically filters queries by tenant_id.

**Features:**

- Automatically filters all QuerySet operations by current tenant
- Automatically sets tenant_id on create() operations
- Works with both ForeignKey('Tenant') and direct tenant_id fields

**Usage:**
Use as the default manager for tenant-isolated models:

```python
from core import TenantManager

class MyModel(models.Model):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)

    objects = TenantManager()  # Tenant-filtered queries
    all_objects = models.Manager()  # Unfiltered queries for admin
```

### TenantIsolatedModel

Abstract base model that provides automatic tenant isolation for Django models.

**Features:**

- Automatically filters queries by tenant_id
- Automatically sets tenant_id on save()
- Validates tenant context on save() and delete()
- Prevents cross-tenant data access
- Provides both filtered (objects) and unfiltered (all_objects) managers

**Usage:**

```python
from core import TenantIsolatedModel

class Widget(TenantIsolatedModel):
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    description = models.TextField()

    class Meta:
        db_table = 'widgets'
```

**Automatic Behavior:**

```python
# Queries are automatically filtered by tenant
widgets = Widget.objects.all()  # Only returns widgets for current tenant

# Creates automatically set tenant_id
widget = Widget.objects.create(name="My Widget")  # tenant_id set automatically

# Cross-tenant access is prevented
widget.tenant_id = "different-tenant"
widget.save()  # Raises TenantIsolationError
```

## Helper Functions

### get_current_tenant()

Returns the current tenant ID from thread-local storage.

```python
from core import get_current_tenant

tenant_id = get_current_tenant()
if tenant_id:
    print(f"Current tenant: {tenant_id}")
```

### set_current_tenant(tenant_id)

Manually set the current tenant ID (useful for background tasks).

```python
from core import set_current_tenant

set_current_tenant("tenant-123")
# Now all queries will be filtered by tenant-123
```

### clear_current_tenant()

Clear the current tenant context.

```python
from core import clear_current_tenant

clear_current_tenant()
# Tenant context is now empty
```

## Error Handling

### TenantIsolationError

Raised when tenant isolation rules are violated.

**Common scenarios:**

- Attempting database operations without tenant context
- Attempting to save/delete objects from a different tenant
- Cross-tenant data access attempts

**Example:**

```python
from core import TenantIsolationError

try:
    widget.save()
except TenantIsolationError as e:
    print(f"Tenant isolation violation: {e}")
```

## Best Practices

1. **Always use TenantIsolatedModel** for models that contain tenant-specific data
2. **Never bypass tenant filtering** unless absolutely necessary (use all_objects manager for admin operations)
3. **Test tenant isolation** thoroughly for all new models and endpoints
4. **Validate tenant context** in service methods that perform database operations
5. **Use set_current_tenant()** in background tasks and management commands

## Testing

When writing tests, you can manually set tenant context:

```python
from core import set_current_tenant, clear_current_tenant

def test_widget_creation():
    # Set tenant context for test
    set_current_tenant("test-tenant")

    try:
        # Create widget - tenant_id will be set automatically
        widget = Widget.objects.create(name="Test Widget")
        assert widget.tenant_id == "test-tenant"
    finally:
        # Clean up tenant context
        clear_current_tenant()
```

## Architecture

The data isolation layer uses a defense-in-depth approach:

1. **Middleware Layer**: Extracts and validates tenant context from authentication
2. **Manager Layer**: Automatically filters QuerySets by tenant_id
3. **Model Layer**: Validates tenant context on save/delete operations
4. **Database Layer**: Foreign key constraints ensure referential integrity

This multi-layered approach ensures that tenant data isolation is enforced at every level, preventing any possibility of cross-tenant data leakage.
