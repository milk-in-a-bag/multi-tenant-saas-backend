# Configuration and Customization Guide

This guide covers every configuration option in the multi-tenant SaaS backend and shows exactly which files to edit for each customization.

**Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8, 17.10**

---

## Environment Variables

All environment variables are loaded from a `.env` file at startup via `python-dotenv`. Copy `.env.example` to `.env` and fill in the values before running the server.

```bash
cp .env.example .env
```

### Required Variables

| Variable       | Description                                                               | Default                                     |
| -------------- | ------------------------------------------------------------------------- | ------------------------------------------- |
| `SECRET_KEY`   | Django cryptographic signing key used for sessions, CSRF, and JWT signing | `django-insecure-change-this-in-production` |
| `DATABASE_URL` | Full PostgreSQL connection URL                                            | _(none — required)_                         |

Generate a secure `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

`DATABASE_URL` format:

```
postgresql://<user>:<password>@<host>:<port>/<dbname>
```

### Application Variables

| Variable               | Description                                         | Default                                       |
| ---------------------- | --------------------------------------------------- | --------------------------------------------- |
| `DEBUG`                | Enables debug mode and detailed error pages         | `True`                                        |
| `ALLOWED_HOSTS`        | Comma-separated list of hostnames Django will serve | `localhost,127.0.0.1`                         |
| `CORS_ALLOWED_ORIGINS` | Comma-separated list of allowed CORS origins        | `http://localhost:3000,http://127.0.0.1:3000` |

### Security Variables (Production)

| Variable                         | Description                                   | Default |
| -------------------------------- | --------------------------------------------- | ------- |
| `SECURE_SSL_REDIRECT`            | Redirect all HTTP requests to HTTPS           | `False` |
| `SECURE_HSTS_SECONDS`            | HSTS max-age in seconds (`31536000` = 1 year) | `0`     |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | Apply HSTS to all subdomains                  | `False` |
| `SECURE_HSTS_PRELOAD`            | Include in browser HSTS preload list          | `False` |
| `SESSION_COOKIE_SECURE`          | Only send session cookie over HTTPS           | `False` |
| `CSRF_COOKIE_SECURE`             | Only send CSRF cookie over HTTPS              | `False` |

---

## Subscription Tiers and Limits

**File to edit:** `tenants/models.py` and `core/middleware.py`

### Changing Tier Names or Adding a New Tier

Subscription tiers are defined in two places that must stay in sync:

**1. `tenants/models.py` — the `SUBSCRIPTION_TIERS` list:**

```python
class Tenant(models.Model):
    SUBSCRIPTION_TIERS = [
        ('free', 'Free'),
        ('professional', 'Professional'),
        ('enterprise', 'Enterprise'),
        ('startup', 'Startup'),   # ← add new tier here
    ]
```

**2. `core/middleware.py` — the `TIER_LIMITS` dict:**

```python
class RateLimitMiddleware(MiddlewareMixin):
    TIER_LIMITS = {
        'free':         100,
        'professional': 1000,
        'enterprise':   10000,
        'startup':      500,    # ← add matching entry here
    }
```

**3. `tenants/services.py` — the `valid_tiers` list in `update_subscription`:**

```python
valid_tiers = ['free', 'professional', 'enterprise', 'startup']  # ← add here too
```

After editing, create and apply a migration:

```bash
python manage.py makemigrations tenants
python manage.py migrate
```

### Gating Features by Tier

To restrict a feature to specific tiers, define a `TIER_FEATURES` dict and check it in your views or services:

```python
# config/settings.py
TIER_FEATURES = {
    'free':         {'widgets', 'audit_logs'},
    'professional': {'widgets', 'audit_logs', 'bulk_export', 'webhooks'},
    'enterprise':   {'widgets', 'audit_logs', 'bulk_export', 'webhooks', 'sso', 'custom_domain'},
    'startup':      {'widgets', 'audit_logs', 'bulk_export'},
}
```

```python
# In any view or service
from django.conf import settings
from tenants.models import Tenant

def require_feature(tenant_id, feature):
    tenant = Tenant.objects.get(id=tenant_id)
    allowed = settings.TIER_FEATURES.get(tenant.subscription_tier, set())
    if feature not in allowed:
        raise PermissionError(f"Feature '{feature}' requires a higher subscription tier")
```

---

## Rate Limit Values

**File to edit:** `core/middleware.py`

The `TIER_LIMITS` dict in `RateLimitMiddleware` maps subscription tier names to requests-per-hour:

```python
class RateLimitMiddleware(MiddlewareMixin):
    # EXTENSION_POINT: rate-limiting-strategies
    TIER_LIMITS = {
        'free':         100,    # ← change these values
        'professional': 1000,
        'enterprise':   10000,
    }
```

No migration is needed — this is a runtime configuration change.

For per-endpoint limits, per-user limits, or Redis-backed distributed rate limiting, see [`docs/extension-points/rate-limiting-strategies.md`](../extension-points/rate-limiting-strategies.md).

---

## Custom Fields on Tenant Registration

**Files to edit:** `tenants/serializers.py`, `tenants/services.py`, `tenants/models.py`

### Step 1 — Add the field to the `Tenant` model

```python
# tenants/models.py
class Tenant(models.Model):
    # ... existing fields ...
    company_name = models.CharField(max_length=255, blank=True, default='')
    billing_email = models.EmailField(blank=True, default='')
```

### Step 2 — Add the field to the registration serializer

```python
# tenants/serializers.py
class TenantRegistrationSerializer(serializers.Serializer):
    identifier    = serializers.CharField(max_length=255)
    admin_email   = serializers.EmailField()
    admin_username = serializers.CharField(max_length=255, required=False)
    company_name  = serializers.CharField(max_length=255, required=False, default='')
    billing_email = serializers.EmailField(required=False, default='')
```

### Step 3 — Pass the fields through in `TenantManager.register_tenant`

```python
# tenants/services.py
@staticmethod
def register_tenant(identifier, admin_email, admin_username=None,
                    company_name='', billing_email=''):
    # ...
    tenant = Tenant.objects.create(
        id=identifier,
        subscription_tier='free',
        subscription_expiration=default_expiration,
        status='active',
        company_name=company_name,
        billing_email=billing_email,
    )
```

### Step 4 — Update the view to pass the new fields

```python
# tenants/views.py  (inside TenantRegistrationView.post)
result = TenantManager.register_tenant(
    identifier=serializer.validated_data['identifier'],
    admin_email=serializer.validated_data['admin_email'],
    admin_username=serializer.validated_data.get('admin_username'),
    company_name=serializer.validated_data.get('company_name', ''),
    billing_email=serializer.validated_data.get('billing_email', ''),
)
```

### Step 5 — Create and apply the migration

```bash
python manage.py makemigrations tenants
python manage.py migrate
```

---

## JWT Token Expiration

**File to edit:** `config/settings.py`

JWT lifetimes are controlled by the `SIMPLE_JWT` dict:

```python
from datetime import timedelta

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME':  timedelta(hours=1),   # ← access token TTL
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),    # ← refresh token TTL
    'ROTATE_REFRESH_TOKENS':  False,  # set True to issue a new refresh token on each use
    'BLACKLIST_AFTER_ROTATION': False,
    'ALGORITHM':    'HS256',
    'SIGNING_KEY':  SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
}
```

Common configurations:

| Scenario              | `ACCESS_TOKEN_LIFETIME` | `REFRESH_TOKEN_LIFETIME` |
| --------------------- | ----------------------- | ------------------------ |
| Default               | `timedelta(hours=1)`    | `timedelta(days=1)`      |
| High-security         | `timedelta(minutes=15)` | `timedelta(hours=8)`     |
| Long-lived CLI tokens | `timedelta(hours=8)`    | `timedelta(days=30)`     |

To rotate refresh tokens (issue a new refresh token on every use and invalidate the old one):

```python
SIMPLE_JWT = {
    # ...
    'ROTATE_REFRESH_TOKENS':    True,
    'BLACKLIST_AFTER_ROTATION': True,
}

# Also add to INSTALLED_APPS:
INSTALLED_APPS = [
    # ...
    'rest_framework_simplejwt.token_blacklist',
]
```

Then run `python manage.py migrate` to create the blacklist tables.

---

## Database Backends

**File to edit:** `config/settings.py` and `.env`

### PostgreSQL (default)

Set `DATABASE_URL` in `.env`:

```dotenv
DATABASE_URL=postgresql://myuser:mypassword@localhost:5432/mydb
```

The settings file parses this URL automatically:

```python
# config/settings.py  (existing code — no changes needed for PostgreSQL)
from urllib.parse import urlparse, parse_qsl

tmpPostgres = urlparse(os.getenv("DATABASE_URL"))
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME':     tmpPostgres.path.replace('/', ''),
        'USER':     tmpPostgres.username,
        'PASSWORD': tmpPostgres.password,
        'HOST':     tmpPostgres.hostname,
        'PORT':     5432,
    }
}
```

### Cloud PostgreSQL (Neon, Supabase, RDS)

Append SSL parameters to the URL:

```dotenv
DATABASE_URL=postgresql://user:pass@host/dbname?sslmode=require
```

The `OPTIONS` dict in `DATABASES` picks these up via `parse_qsl(tmpPostgres.query)`.

For Neon or other serverless Postgres providers that don't support `CREATE DATABASE`, the test database is configured to reuse the same database name:

```python
'TEST': {
    'NAME': _db_name,   # reuse the same DB for tests
},
```

### SQLite (development / CI only)

SQLite is not recommended for production but works for quick local testing without PostgreSQL:

```python
# config/settings.py
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
```

> **Warning:** The `SELECT FOR UPDATE` used by `RateLimitMiddleware` is not supported by SQLite. Disable rate limiting in SQLite environments or mock it in tests.

### Connection Pooling (PgBouncer / pgpool)

Add `CONN_MAX_AGE` to keep connections alive between requests:

```python
DATABASES = {
    'default': {
        # ... existing config ...
        'CONN_MAX_AGE': 60,   # seconds; 0 = close after each request
    }
}
```

For PgBouncer in transaction-pooling mode, also set:

```python
'DISABLE_SERVER_SIDE_CURSORS': True,   # already set in the default config
```

---

## Audit Log Retention

**File to edit:** `core/management/commands/cleanup_audit_logs.py` (or pass `--days` at runtime)

The default retention period is **90 days**. Logs older than this are deleted by the `cleanup_audit_logs` management command.

### Running the Cleanup Command

```bash
# Delete logs older than 90 days (default)
python manage.py cleanup_audit_logs

# Preview without deleting
python manage.py cleanup_audit_logs --dry-run

# Custom retention period (e.g. 180 days)
python manage.py cleanup_audit_logs --days 180
```

### Changing the Default Retention Period

Edit the `--days` default in the management command:

```python
# core/management/commands/cleanup_audit_logs.py
def add_arguments(self, parser):
    parser.add_argument(
        '--days',
        type=int,
        default=180,   # ← change the default here
        help='Retention period in days (default: 180)',
    )
```

### Scheduling Automatic Cleanup

Run the command daily via cron:

```cron
# crontab -e
0 2 * * * /path/to/venv/bin/python /path/to/project/manage.py cleanup_audit_logs >> /var/log/audit_cleanup.log 2>&1
```

Or with a task scheduler like Celery Beat:

```python
# celery_config.py
from celery.schedules import crontab

CELERYBEAT_SCHEDULE = {
    'cleanup-audit-logs': {
        'task': 'myapp.tasks.cleanup_audit_logs',
        'schedule': crontab(hour=2, minute=0),  # daily at 02:00 UTC
    },
}
```

```python
# myapp/tasks.py
from celery import shared_task
from django.core.management import call_command

@shared_task
def cleanup_audit_logs():
    call_command('cleanup_audit_logs', days=90)
```

---

## Custom Health Check Validations

**File to edit:** `api/health.py`

The default health check verifies only the database connection. Add custom checks by extending the `health_check` view.

### Adding a Cache Check

```python
# api/health.py
from django.core.cache import cache

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def health_check(request):
    db_status = "healthy"
    cache_status = "healthy"

    # Database check
    try:
        connection.ensure_connection()
    except OperationalError:
        db_status = "unhealthy"

    # Cache check
    try:
        cache.set('health_check', 'ok', timeout=5)
        if cache.get('health_check') != 'ok':
            cache_status = "unhealthy"
    except Exception:
        cache_status = "unhealthy"

    overall_status = "healthy" if all(
        s == "healthy" for s in [db_status, cache_status]
    ) else "unhealthy"
    http_status = 200 if overall_status == "healthy" else 503

    return Response(
        {
            "status":    overall_status,
            "database":  db_status,
            "cache":     cache_status,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        },
        status=http_status,
    )
```

### Adding an External Service Check

```python
# api/health.py
import httpx

def _check_external_service(url: str, timeout: float = 2.0) -> str:
    try:
        response = httpx.get(url, timeout=timeout)
        return "healthy" if response.status_code < 500 else "unhealthy"
    except Exception:
        return "unhealthy"

@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
def health_check(request):
    db_status       = _check_database()
    payments_status = _check_external_service("https://status.stripe.com/api/v2/status.json")

    overall_status = "healthy" if all(
        s == "healthy" for s in [db_status, payments_status]
    ) else "unhealthy"

    return Response(
        {
            "status":   overall_status,
            "database": db_status,
            "payments": payments_status,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        },
        status=200 if overall_status == "healthy" else 503,
    )
```

> **Note:** Keep health checks fast. The endpoint must respond within 100 ms (Requirement 9.4). Use short timeouts on external checks and consider making them non-blocking if they are slow.

---

## Common Configuration Scenarios

### Development

`.env` for local development:

```dotenv
SECRET_KEY=dev-only-insecure-key-change-before-production
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/multitenant_saas
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

`config/settings.py` additions for development convenience:

```python
if DEBUG:
    # Show SQL queries in the console
    LOGGING = {
        'version': 1,
        'handlers': {'console': {'class': 'logging.StreamHandler'}},
        'loggers': {
            'django.db.backends': {
                'handlers': ['console'],
                'level': 'DEBUG',
            },
        },
    }
```

### Staging

`.env` for a staging environment:

```dotenv
SECRET_KEY=<unique-staging-secret>
DEBUG=False
ALLOWED_HOSTS=staging.example.com
DATABASE_URL=postgresql://user:pass@staging-db.example.com:5432/saas_staging
CORS_ALLOWED_ORIGINS=https://staging-app.example.com
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

### Production

`.env` for production:

```dotenv
SECRET_KEY=<long-random-secret-never-committed-to-git>
DEBUG=False
ALLOWED_HOSTS=api.example.com
DATABASE_URL=postgresql://user:pass@prod-db.example.com:5432/saas_prod?sslmode=require
CORS_ALLOWED_ORIGINS=https://app.example.com
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

Additional `config/settings.py` settings for production:

```python
# Serve static files from a CDN or object storage
STATIC_URL  = 'https://cdn.example.com/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Structured logging for log aggregation (e.g. Datadog, CloudWatch)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
```

### Docker / Container Deployment

Pass environment variables via `docker run -e` or a `docker-compose.yml`:

```yaml
# docker-compose.yml
services:
  web:
    build: .
    environment:
      SECRET_KEY: "${SECRET_KEY}"
      DEBUG: "False"
      ALLOWED_HOSTS: "api.example.com"
      DATABASE_URL: "postgresql://user:pass@db:5432/saas"
    depends_on:
      - db
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: saas
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
```

---

## Further Reading

- [`docs/extension-points/rate-limiting-strategies.md`](../extension-points/rate-limiting-strategies.md) — per-endpoint, per-user, and Redis-backed rate limiting
- [`docs/extension-points/subscription-features.md`](../extension-points/subscription-features.md) — feature flags per subscription tier
- [`docs/extension-points/tenant-provisioning.md`](../extension-points/tenant-provisioning.md) — custom logic on tenant creation
- [`docs/extension-points/audit-log-processors.md`](../extension-points/audit-log-processors.md) — forwarding audit events to external systems
- [`docs/developer-guide/architecture.md`](architecture.md) — system architecture and component overview
- [`docs/developer-guide/quickstart.md`](quickstart.md) — running the system locally
