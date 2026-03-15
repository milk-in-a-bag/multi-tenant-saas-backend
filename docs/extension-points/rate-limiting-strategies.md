# Extension Point: Custom Rate Limiting Strategies

**Requirement: 13.3**

This document explains how to customize or replace the built-in per-tenant hourly rate limiting.

---

## Overview

The built-in `RateLimitMiddleware` in `core/middleware.py` enforces a fixed hourly window counter stored in the `rate_limits` table:

| Subscription tier | Requests / hour |
| ----------------- | --------------- |
| `free`            | 100             |
| `professional`    | 1,000           |
| `enterprise`      | 10,000          |

When a subscription expires the tenant is automatically downgraded to `free` tier limits.

You can extend this in several ways:

1. **Change tier limits** — edit `TIER_LIMITS` in `RateLimitMiddleware`
2. **Add per-endpoint limits** — subclass `RateLimitMiddleware` and override `_get_limit`
3. **Replace the algorithm** — swap the fixed-window counter for sliding-window or token-bucket
4. **Add per-user limits** — track limits by `(tenant_id, user_id)` instead of just `tenant_id`

---

## Where to Make Changes

| File                 | What to change                                                  |
| -------------------- | --------------------------------------------------------------- |
| `core/middleware.py` | Modify `RateLimitMiddleware` or add a new middleware class      |
| `core/models.py`     | Extend `RateLimit` model if you need additional tracking fields |
| `config/settings.py` | Register new middleware in `MIDDLEWARE`                         |

---

## Extension Point Marker

```python
# EXTENSION_POINT: rate-limiting-strategies
# Customize rate limiting behaviour here.
# Options:
#   1. Change TIER_LIMITS to adjust per-tier quotas
#   2. Override _get_limit(tenant, request) for per-endpoint or per-user limits
#   3. Replace the fixed-window algorithm with sliding-window or token-bucket
#   4. Add Redis-backed counters for distributed deployments
# See: docs/extension-points/rate-limiting-strategies.md
```

This comment lives at the top of `RateLimitMiddleware` in `core/middleware.py`.

---

## Example 1: Changing Tier Limits

The simplest customization — just update the `TIER_LIMITS` dict:

```python
# core/middleware.py

class RateLimitMiddleware(MiddlewareMixin):
    # EXTENSION_POINT: rate-limiting-strategies
    TIER_LIMITS = {
        "free":         50,      # tighter free tier
        "professional": 5_000,   # more generous professional tier
        "enterprise":   100_000, # high-volume enterprise tier
    }
```

---

## Example 2: Per-Endpoint Rate Limits

Override `_get_limit` to return different limits based on the request path:

```python
# core/middleware.py

class RateLimitMiddleware(MiddlewareMixin):
    # EXTENSION_POINT: rate-limiting-strategies
    TIER_LIMITS = {
        "free":         100,
        "professional": 1000,
        "enterprise":   10000,
    }

    # Extra-tight limits for expensive endpoints
    ENDPOINT_LIMITS = {
        "/api/reports/export": {"free": 5, "professional": 50, "enterprise": 500},
        "/api/widgets/bulk":   {"free": 10, "professional": 100, "enterprise": 1000},
    }

    def _get_limit(self, tenant, request):
        """Return the effective rate limit for this tenant + endpoint combination."""
        tier = tenant.subscription_tier
        for prefix, limits in self.ENDPOINT_LIMITS.items():
            if request.path.startswith(prefix):
                return limits.get(tier, self.TIER_LIMITS.get(tier, 100))
        return self.TIER_LIMITS.get(tier, 100)
```

Then call `self._get_limit(tenant, request)` instead of `self.TIER_LIMITS.get(...)` in `process_request`.

---

## Example 3: Per-User Rate Limits

Track limits by `(tenant_id, user_id)` to prevent a single user from consuming the whole tenant quota:

```python
# core/models.py

class UserRateLimit(models.Model):
    """Per-user rate limit tracking (supplement to per-tenant limits)."""
    tenant = models.ForeignKey("tenants.Tenant", on_delete=models.CASCADE, db_column="tenant_id")
    user_id = models.UUIDField()
    request_count = models.IntegerField(default=0)
    window_start = models.DateTimeField()

    class Meta:
        db_table = "user_rate_limits"
        unique_together = [("tenant", "user_id")]
```

```python
# core/middleware.py

from core.models import UserRateLimit

class PerUserRateLimitMiddleware(MiddlewareMixin):
    """
    Enforce per-user rate limits in addition to per-tenant limits.
    Add this AFTER RateLimitMiddleware in settings.MIDDLEWARE.
    """

    USER_TIER_LIMITS = {
        "free":         20,   # per user, per hour
        "professional": 200,
        "enterprise":   2000,
    }

    def process_request(self, request):
        from core.middleware import get_current_tenant
        from tenants.models import Tenant
        from django.utils import timezone
        from django.db import transaction

        tenant_id = get_current_tenant()
        if not tenant_id or not hasattr(request, "user") or not request.user.is_authenticated:
            return None

        try:
            tenant = Tenant.objects.get(id=tenant_id)
            limit = self.USER_TIER_LIMITS.get(tenant.subscription_tier, 20)
            now = timezone.now()
            window_start = now.replace(minute=0, second=0, microsecond=0)

            with transaction.atomic():
                record, _ = UserRateLimit.objects.select_for_update().get_or_create(
                    tenant_id=tenant_id,
                    user_id=request.user.id,
                    defaults={"request_count": 0, "window_start": window_start},
                )
                if record.window_start < window_start:
                    record.request_count = 0
                    record.window_start = window_start

                if record.request_count >= limit:
                    from django.http import JsonResponse
                    next_window = window_start + timezone.timedelta(hours=1)
                    retry_after = int((next_window - now).total_seconds())
                    resp = JsonResponse(
                        {"error": {"code": "USER_RATE_LIMIT_EXCEEDED",
                                   "message": f"Per-user limit of {limit} req/hr exceeded"}},
                        status=429,
                    )
                    resp["Retry-After"] = str(retry_after)
                    return resp

                record.request_count += 1
                record.save()

        except Exception:
            pass  # never block a request due to rate-limit errors

        return None
```

Register in `config/settings.py`:

```python
MIDDLEWARE = [
    "core.middleware.TenantContextMiddleware",
    "core.middleware.RateLimitMiddleware",
    "core.middleware.PerUserRateLimitMiddleware",  # ← add after tenant rate limit
    # ...
]
```

---

## Example 4: Redis-Backed Sliding-Window Counter

For distributed deployments where multiple Django processes share a Redis instance:

```python
# core/middleware.py

import redis
import time
from django.conf import settings
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from core.middleware import get_current_tenant


class RedisRateLimitMiddleware(MiddlewareMixin):
    """
    Sliding-window rate limiter backed by Redis.
    Replaces the database-backed RateLimitMiddleware for distributed deployments.

    Requires:  pip install redis
    Settings:  REDIS_URL = "redis://localhost:6379/0"
    """

    TIER_LIMITS = {
        "free":         100,
        "professional": 1000,
        "enterprise":   10000,
    }
    WINDOW_SECONDS = 3600  # 1 hour

    def __init__(self, get_response=None):
        super().__init__(get_response)
        self._redis = redis.from_url(getattr(settings, "REDIS_URL", "redis://localhost:6379/0"))

    def process_request(self, request):
        tenant_id = get_current_tenant()
        if not tenant_id:
            return None

        try:
            from tenants.models import Tenant
            from django.utils import timezone

            tenant = Tenant.objects.get(id=tenant_id)
            limit = self.TIER_LIMITS.get(tenant.subscription_tier, 100)

            key = f"ratelimit:{tenant_id}"
            now = time.time()
            window_start = now - self.WINDOW_SECONDS

            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)   # remove old entries
            pipe.zadd(key, {str(now): now})               # add current request
            pipe.zcard(key)                               # count in window
            pipe.expire(key, self.WINDOW_SECONDS + 60)    # TTL cleanup
            _, _, count, _ = pipe.execute()

            if count > limit:
                retry_after = int(self.WINDOW_SECONDS - (now - window_start))
                resp = JsonResponse(
                    {"error": {"code": "RATE_LIMIT_EXCEEDED",
                               "message": f"Rate limit of {limit} req/hr exceeded"}},
                    status=429,
                )
                resp["Retry-After"] = str(retry_after)
                return resp

        except Exception:
            pass  # degrade gracefully

        return None
```

Replace `RateLimitMiddleware` in `config/settings.py`:

```python
MIDDLEWARE = [
    "core.middleware.TenantContextMiddleware",
    "core.middleware.RedisRateLimitMiddleware",  # replaces RateLimitMiddleware
    # ...
]
```

---

## Testing Custom Rate Limiting

```python
# core/tests/test_rate_limit_middleware.py

from django.test import TestCase, RequestFactory
from unittest.mock import patch, MagicMock
from core.middleware import RateLimitMiddleware
from tenants.models import Tenant
from django.utils import timezone
from datetime import timedelta


class CustomRateLimitTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            id="test-tenant",
            subscription_tier="free",
            subscription_expiration=timezone.now() + timedelta(days=365),
        )
        self.factory = RequestFactory()
        self.middleware = RateLimitMiddleware(get_response=lambda r: None)

    @patch("core.middleware.get_current_tenant", return_value="test-tenant")
    def test_free_tier_limit_is_100(self, _):
        from core.models import RateLimit
        RateLimit.objects.create(
            tenant_id="test-tenant",
            request_count=100,
            window_start=timezone.now().replace(minute=0, second=0, microsecond=0),
        )
        request = self.factory.get("/api/widgets/")
        response = self.middleware.process_request(request)
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)
```

---

## Related Files

- `core/middleware.py` — `RateLimitMiddleware` implementation
- `core/models.py` — `RateLimit` model
- `tenants/models.py` — `Tenant.subscription_tier` field
- `docs/developer-guide/architecture.md` — rate limiting section
