# Extension Point: Custom Subscription Tier Features

**Requirement: 13.6**

This document explains how to add tier-specific features and capabilities to the subscription model.

---

## Overview

The system ships with three subscription tiers defined on the `Tenant` model in `tenants/models.py`:

| Tier           | Rate limit    | Default expiration           |
| -------------- | ------------- | ---------------------------- |
| `free`         | 100 req/hr    | 1 year from registration     |
| `professional` | 1,000 req/hr  | Set by `update_subscription` |
| `enterprise`   | 10,000 req/hr | Set by `update_subscription` |

Beyond rate limits, you can gate any feature behind a tier check. Common patterns:

- Feature flags (enable/disable entire features per tier)
- Resource quotas (max widgets, max users, max API keys)
- UI/API capability differences (export, bulk operations, webhooks)
- SLA-based behaviour (priority support queue, dedicated infrastructure)

---

## Where to Make Changes

| File                            | What to change                                     |
| ------------------------------- | -------------------------------------------------- |
| `tenants/models.py`             | Add tier constants or a feature-flag helper method |
| `authentication/permissions.py` | Add a `RequiresTier` permission class              |
| `core/middleware.py`            | Optionally enforce quotas in middleware            |
| `<app>/views.py`                | Apply tier permission classes to specific views    |

---

## Extension Point Marker

```python
# EXTENSION_POINT: subscription-features
# Add tier-specific feature logic here.
# Options:
#   1. Add a TIER_FEATURES dict to Tenant or a separate FeatureFlag model
#   2. Add a RequiresTier DRF permission class in authentication/permissions.py
#   3. Add quota checks in service methods (e.g., max widgets per tenant)
# See: docs/extension-points/subscription-features.md
```

This comment lives in `tenants/models.py` below the `SUBSCRIPTION_TIERS` constant.

---

## Example 1: Feature Flag Dictionary

Define which features are available per tier in one place:

```python
# tenants/models.py

class Tenant(models.Model):
    SUBSCRIPTION_TIERS = [
        ("free",         "Free"),
        ("professional", "Professional"),
        ("enterprise",   "Enterprise"),
    ]

    # EXTENSION_POINT: subscription-features
    # Add new features here and set which tiers can access them.
    TIER_FEATURES = {
        "free": {
            "max_widgets":    10,
            "api_export":     False,
            "webhooks":       False,
            "bulk_import":    False,
            "sso":            False,
            "audit_log_days": 30,
        },
        "professional": {
            "max_widgets":    500,
            "api_export":     True,
            "webhooks":       True,
            "bulk_import":    False,
            "sso":            False,
            "audit_log_days": 90,
        },
        "enterprise": {
            "max_widgets":    None,   # unlimited
            "api_export":     True,
            "webhooks":       True,
            "bulk_import":    True,
            "sso":            True,
            "audit_log_days": 365,
        },
    }

    def has_feature(self, feature_name):
        """Return True if this tenant's tier includes the given feature."""
        features = self.TIER_FEATURES.get(self.subscription_tier, {})
        value = features.get(feature_name, False)
        return bool(value)

    def get_feature_limit(self, feature_name):
        """Return the numeric limit for a feature, or None for unlimited."""
        features = self.TIER_FEATURES.get(self.subscription_tier, {})
        return features.get(feature_name)
```

Use it in a service:

```python
# widgets/services.py

from tenants.models import Tenant
from rest_framework.exceptions import ValidationError


def create_widget(tenant_id, user_id, data):
    tenant = Tenant.objects.get(id=tenant_id)
    max_widgets = tenant.get_feature_limit("max_widgets")

    if max_widgets is not None:
        from widgets.models import Widget
        current_count = Widget.objects.filter(tenant_id=tenant_id).count()
        if current_count >= max_widgets:
            raise ValidationError({
                "error": {
                    "code": "QUOTA_EXCEEDED",
                    "message": (
                        f"Your {tenant.subscription_tier} plan allows a maximum "
                        f"of {max_widgets} widgets. Upgrade to create more."
                    ),
                }
            })
    # ... rest of create logic
```

---

## Example 2: Tier-Gated DRF Permission Class

```python
# authentication/permissions.py

from rest_framework import permissions
from rest_framework.exceptions import PermissionDenied
from tenants.models import Tenant


class RequiresFeature(permissions.BasePermission):
    """
    Deny access unless the tenant's subscription tier includes the named feature.

    Usage:
        class WebhookView(APIView):
            permission_classes = [IsAuthenticated, RequiresFeature]
            required_feature = "webhooks"
    """

    def has_permission(self, request, view):
        feature = getattr(view, "required_feature", None)
        if not feature:
            return True  # no feature requirement set on this view

        tenant_id = getattr(request.user, "tenant_id", None)
        if not tenant_id:
            return False

        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            return False

        if tenant.has_feature(feature):
            return True

        raise PermissionDenied({
            "error": {
                "code": "FEATURE_NOT_AVAILABLE",
                "message": (
                    f"The '{feature}' feature is not available on your "
                    f"{tenant.subscription_tier} plan. Please upgrade."
                ),
            }
        })
```

Apply it to a view:

```python
# widgets/views.py

from authentication.permissions import RoleBasedPermission, RequiresFeature

class WidgetExportView(APIView):
    permission_classes = [RoleBasedPermission, RequiresFeature]
    required_feature = "api_export"

    def get(self, request):
        # Only professional and enterprise tenants reach here
        ...
```

---

## Example 3: Quota Enforcement Middleware

For quotas that should be checked on every request (e.g., storage limits), add a lightweight middleware:

```python
# core/middleware.py

class QuotaMiddleware(MiddlewareMixin):
    """
    Check resource quotas before processing write requests.
    Add after RateLimitMiddleware in settings.MIDDLEWARE.
    """

    def process_request(self, request):
        if request.method not in ("POST", "PUT", "PATCH"):
            return None

        tenant_id = get_current_tenant()
        if not tenant_id:
            return None

        # EXTENSION_POINT: subscription-features
        # Add quota checks here for write operations
        # Example: check widget count before allowing POST /api/widgets/
        if request.path.startswith("/api/widgets/") and request.method == "POST":
            return self._check_widget_quota(tenant_id)

        return None

    def _check_widget_quota(self, tenant_id):
        try:
            from tenants.models import Tenant
            from widgets.models import Widget
            from django.http import JsonResponse

            tenant = Tenant.objects.get(id=tenant_id)
            max_widgets = tenant.get_feature_limit("max_widgets")
            if max_widgets is None:
                return None  # unlimited

            count = Widget.objects.filter(tenant_id=tenant_id).count()
            if count >= max_widgets:
                return JsonResponse(
                    {"error": {"code": "QUOTA_EXCEEDED",
                               "message": f"Widget limit of {max_widgets} reached."}},
                    status=403,
                )
        except Exception:
            pass
        return None
```

---

## Example 4: Exposing Tier Features in the API

Return the tenant's available features in the tenant config endpoint so clients can adapt their UI:

```python
# tenants/serializers.py  (extend TenantConfigSerializer)

from tenants.models import Tenant

class TenantConfigSerializer(serializers.Serializer):
    tenant_id           = serializers.CharField()
    subscription_tier   = serializers.CharField()
    subscription_expiration = serializers.DateTimeField()
    rate_limit          = serializers.IntegerField()
    status              = serializers.CharField()
    created_at          = serializers.DateTimeField()

    # EXTENSION_POINT: subscription-features
    features = serializers.SerializerMethodField()

    def get_features(self, obj):
        """Return the feature set for the tenant's current tier."""
        tenant = Tenant.objects.get(id=obj["tenant_id"])
        return Tenant.TIER_FEATURES.get(tenant.subscription_tier, {})
```

---

## Adding a New Subscription Tier

To add a fourth tier (e.g., `starter`):

1. Add it to `Tenant.SUBSCRIPTION_TIERS` and `TIER_FEATURES`
2. Add it to `RateLimitMiddleware.TIER_LIMITS` in `core/middleware.py`
3. Add it to `TenantManager.update_subscription` validation list in `tenants/services.py`
4. Generate and apply a migration if you added a `CHECK` constraint

```python
# tenants/models.py
SUBSCRIPTION_TIERS = [
    ("free",         "Free"),
    ("starter",      "Starter"),      # ← new tier
    ("professional", "Professional"),
    ("enterprise",   "Enterprise"),
]

TIER_FEATURES = {
    "starter": {
        "max_widgets":    50,
        "api_export":     False,
        "webhooks":       False,
        "bulk_import":    False,
        "sso":            False,
        "audit_log_days": 60,
    },
    # ... existing tiers
}
```

```python
# core/middleware.py
TIER_LIMITS = {
    "free":         100,
    "starter":      300,    # ← new tier
    "professional": 1000,
    "enterprise":   10000,
}
```

---

## Testing Subscription Features

```python
# tenants/tests.py

from django.test import TestCase
from rest_framework.test import APIClient
from tenants.models import Tenant
from authentication.models import User
from django.utils import timezone
from datetime import timedelta


class SubscriptionFeatureTest(TestCase):
    def setUp(self):
        self.free_tenant = Tenant.objects.create(
            id="free-corp",
            subscription_tier="free",
            subscription_expiration=timezone.now() + timedelta(days=365),
        )
        self.pro_tenant = Tenant.objects.create(
            id="pro-corp",
            subscription_tier="professional",
            subscription_expiration=timezone.now() + timedelta(days=365),
        )

    def test_free_tenant_does_not_have_webhooks(self):
        self.assertFalse(self.free_tenant.has_feature("webhooks"))

    def test_professional_tenant_has_webhooks(self):
        self.assertTrue(self.pro_tenant.has_feature("webhooks"))

    def test_free_tenant_max_widgets_is_10(self):
        self.assertEqual(self.free_tenant.get_feature_limit("max_widgets"), 10)

    def test_enterprise_tenant_has_unlimited_widgets(self):
        enterprise = Tenant.objects.create(
            id="ent-corp",
            subscription_tier="enterprise",
            subscription_expiration=timezone.now() + timedelta(days=365),
        )
        self.assertIsNone(enterprise.get_feature_limit("max_widgets"))
```

---

## Related Files

- `tenants/models.py` — `Tenant` model with `SUBSCRIPTION_TIERS`
- `tenants/services.py` — `TenantManager.update_subscription`
- `core/middleware.py` — `RateLimitMiddleware.TIER_LIMITS`
- `authentication/permissions.py` — DRF permission classes
- `docs/developer-guide/architecture.md` — rate limiting and subscription tier table
