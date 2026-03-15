# Extension Point: Custom Tenant Provisioning Logic

**Requirement: 13.4**

This document explains how to add custom logic that runs when a new tenant is registered.

---

## Overview

When a tenant registers, `TenantManager.register_tenant` in `tenants/services.py`:

1. Creates the `Tenant` record with `subscription_tier='free'`
2. Creates an initial admin `User`
3. Logs a `tenant_registered` audit event
4. Returns the tenant ID and temporary admin credentials

You can extend this to run additional setup steps such as:

- Seeding default data (categories, templates, settings)
- Sending a welcome email
- Creating a Stripe/billing customer record
- Provisioning external resources (S3 bucket, subdomain, etc.)
- Notifying an internal Slack channel

---

## Where to Make Changes

| File                  | What to change                                              |
| --------------------- | ----------------------------------------------------------- |
| `tenants/services.py` | Add provisioning steps inside `register_tenant`             |
| `tenants/models.py`   | Add fields to `Tenant` if provisioning needs to store state |

---

## Extension Point Marker

```python
# EXTENSION_POINT: tenant-provisioning
# Add custom tenant setup logic here, inside the transaction.atomic() block
# in TenantManager.register_tenant so that failures roll back the whole
# registration atomically.
# Examples: seed default data, create billing customer, send welcome email.
# See: docs/extension-points/tenant-provisioning.md
```

This comment lives inside `TenantManager.register_tenant` in `tenants/services.py`.

---

## Example 1: Seeding Default Data

Create default records for every new tenant (e.g., a "General" category):

```python
# tenants/services.py  (inside register_tenant, within transaction.atomic())

# EXTENSION_POINT: tenant-provisioning
# Seed default categories for every new tenant
from widgets.models import Widget  # replace with your own model

Widget.objects.create(
    tenant_id=identifier,
    name="Getting Started",
    description="Your first widget — feel free to edit or delete it.",
    created_by=admin_user,
)
```

---

## Example 2: Sending a Welcome Email

```python
# tenants/services.py

from django.core.mail import send_mail
from django.conf import settings

# EXTENSION_POINT: tenant-provisioning
# Send welcome email after successful registration
send_mail(
    subject="Welcome to MyApp",
    message=(
        f"Hi {admin_username},\n\n"
        f"Your tenant '{identifier}' is ready.\n"
        f"Temporary password: {temp_password}\n\n"
        "Please change your password on first login."
    ),
    from_email=settings.DEFAULT_FROM_EMAIL,
    recipient_list=[admin_email],
    fail_silently=True,  # don't fail registration if email fails
)
```

---

## Example 3: Creating a Billing Customer

Integrate with Stripe (or any billing provider) during registration:

```python
# tenants/services.py

import stripe
from django.conf import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

# EXTENSION_POINT: tenant-provisioning
# Create a Stripe customer for billing
stripe_customer = stripe.Customer.create(
    email=admin_email,
    name=identifier,
    metadata={"tenant_id": identifier},
)

# Store the Stripe customer ID on the tenant
tenant.stripe_customer_id = stripe_customer["id"]
tenant.save()
```

Add the field to the `Tenant` model first:

```python
# tenants/models.py

class Tenant(models.Model):
    # ... existing fields ...

    # EXTENSION_POINT: tenant-provisioning
    # Add fields here to store provisioning state
    stripe_customer_id = models.CharField(max_length=255, blank=True, default="")
    onboarding_completed = models.BooleanField(default=False)
```

Then generate and apply a migration:

```bash
python manage.py makemigrations tenants
python manage.py migrate
```

---

## Example 4: Full Custom Provisioning Hook

For complex provisioning, extract the logic into a dedicated function so `register_tenant` stays readable:

```python
# tenants/provisioning.py  (new file)

from django.core.mail import send_mail
from django.conf import settings
import stripe


def provision_new_tenant(tenant, admin_user, temp_password):
    """
    Run all custom setup steps for a newly registered tenant.
    Called inside the register_tenant transaction — raise an exception
    to roll back the entire registration.
    """
    _seed_default_data(tenant, admin_user)
    _create_billing_customer(tenant, admin_user)
    _send_welcome_email(tenant, admin_user, temp_password)


def _seed_default_data(tenant, admin_user):
    from widgets.models import Widget
    Widget.objects.create(
        tenant_id=tenant.id,
        name="Getting Started",
        description="Your first widget.",
        created_by=admin_user,
    )


def _create_billing_customer(tenant, admin_user):
    stripe.api_key = settings.STRIPE_SECRET_KEY
    customer = stripe.Customer.create(
        email=admin_user.email,
        name=tenant.id,
        metadata={"tenant_id": tenant.id},
    )
    tenant.stripe_customer_id = customer["id"]
    tenant.save()


def _send_welcome_email(tenant, admin_user, temp_password):
    send_mail(
        subject="Welcome to MyApp",
        message=f"Tenant: {tenant.id}\nPassword: {temp_password}",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[admin_user.email],
        fail_silently=True,
    )
```

Call it from `register_tenant`:

```python
# tenants/services.py  (inside transaction.atomic())

# EXTENSION_POINT: tenant-provisioning
from tenants.provisioning import provision_new_tenant
provision_new_tenant(tenant, admin_user, temp_password)
```

---

## Keeping Provisioning Atomic

All provisioning steps inside `transaction.atomic()` will roll back if any step raises an exception. Steps that call external services (email, Stripe) should use `fail_silently=True` or be moved **outside** the transaction if partial failure is acceptable:

```python
# tenants/services.py

with transaction.atomic():
    tenant = Tenant.objects.create(...)
    admin_user = User.objects.create_user(...)
    _seed_default_data(tenant, admin_user)   # inside transaction — rolls back on failure
    # EXTENSION_POINT: tenant-provisioning — add DB-only steps here

# Outside transaction — external calls that should not block registration
_send_welcome_email(tenant, admin_user, temp_password)
_notify_slack(tenant)
```

---

## Testing Custom Provisioning

```python
# tenants/tests.py

from django.test import TestCase
from unittest.mock import patch, MagicMock
from tenants.services import TenantManager


class TenantProvisioningTest(TestCase):

    @patch("tenants.provisioning._send_welcome_email")
    @patch("tenants.provisioning._create_billing_customer")
    def test_registration_seeds_default_widget(self, mock_billing, mock_email):
        result = TenantManager.register_tenant(
            identifier="new-corp",
            admin_email="admin@new-corp.com",
        )
        self.assertEqual(result["tenant_id"], "new-corp")

        from widgets.models import Widget
        from core.middleware import set_current_tenant
        set_current_tenant("new-corp")
        widgets = Widget.objects.filter(tenant_id="new-corp")
        self.assertEqual(widgets.count(), 1)
        self.assertEqual(widgets.first().name, "Getting Started")

    @patch("stripe.Customer.create", side_effect=Exception("Stripe down"))
    def test_stripe_failure_rolls_back_registration(self, _):
        from tenants.models import Tenant
        with self.assertRaises(Exception):
            TenantManager.register_tenant(
                identifier="fail-corp",
                admin_email="admin@fail-corp.com",
            )
        self.assertFalse(Tenant.objects.filter(id="fail-corp").exists())
```

---

## Related Files

- `tenants/services.py` — `TenantManager.register_tenant`
- `tenants/models.py` — `Tenant` model
- `authentication/models.py` — `User` model created during provisioning
- `core/audit_logger.py` — `AuditLogger.log_event` for logging provisioning steps
