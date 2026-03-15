# Deployment Guide

This guide covers deploying the multi-tenant SaaS backend to a production environment.

**Requirements: 12.9**

---

## Environment Configuration for Production

Copy `.env.example` to a secure location (never commit it to version control) and set the following values:

```dotenv
# Required
SECRET_KEY=<long-random-secret>          # python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
DEBUG=False
ALLOWED_HOSTS=api.example.com

# Database
DATABASE_URL=postgresql://user:pass@db.example.com:5432/saas_prod?sslmode=require

# CORS
CORS_ALLOWED_ORIGINS=https://app.example.com

# HTTPS / Security headers
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

> **Never set `DEBUG=True` in production.** It exposes stack traces and internal settings to anyone who triggers an error.

See [`docs/developer-guide/configuration.md`](configuration.md) for the full variable reference.

---

## Database Setup and Connection Pooling

### Initial Setup

Create the production database and a dedicated application user with least-privilege access:

```sql
-- Run as a PostgreSQL superuser
CREATE DATABASE saas_prod;
CREATE USER saas_app WITH PASSWORD '<strong-password>';
GRANT CONNECT ON DATABASE saas_prod TO saas_app;
\c saas_prod
GRANT USAGE ON SCHEMA public TO saas_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO saas_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO saas_app;
```

Run migrations on first deploy (and on every subsequent deploy that includes schema changes):

```bash
python manage.py migrate --no-input
```

### Connection Pooling

For production workloads, use [PgBouncer](https://www.pgbouncer.org/) in **transaction pooling** mode to reduce connection overhead. The default settings already include `DISABLE_SERVER_SIDE_CURSORS=True`, which is required for PgBouncer transaction mode.

Add `CONN_MAX_AGE` to keep Django's own connection alive between requests when not using PgBouncer:

```python
# config/settings.py
DATABASES = {
    'default': {
        # ... existing config ...
        'CONN_MAX_AGE': 60,  # seconds; 0 = close after each request
    }
}
```

For cloud-managed databases (AWS RDS, Neon, Supabase), append `?sslmode=require` to `DATABASE_URL` and consider `?connect_timeout=10` to fail fast on connection issues.

---

## HTTPS and Security Configuration

Django's `SecurityMiddleware` (already first in `MIDDLEWARE`) handles HTTPS redirects and security headers when the environment variables above are set.

### TLS Termination

Terminate TLS at a reverse proxy (nginx, Caddy, AWS ALB) rather than in Django. Configure the proxy to:

1. Redirect HTTP → HTTPS (301).
2. Forward `X-Forwarded-Proto: https` so Django knows the original scheme.
3. Set `SECURE_PROXY_SSL_HEADER` in settings if using a proxy:

```python
# config/settings.py
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
```

### Security Headers Checklist

With the production `.env` above, Django automatically sends:

| Header                      | Value                                          | Set by                        |
| --------------------------- | ---------------------------------------------- | ----------------------------- |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` | `SECURE_HSTS_*` settings      |
| `X-Content-Type-Options`    | `nosniff`                                      | `SECURE_CONTENT_TYPE_NOSNIFF` |
| `X-Frame-Options`           | `DENY`                                         | `X_FRAME_OPTIONS`             |
| `X-XSS-Protection`          | `1; mode=block`                                | `SECURE_BROWSER_XSS_FILTER`   |

Add `Content-Security-Policy` at the reverse proxy level for additional protection.

---

## Static File Serving

Django does not serve static files efficiently in production. Collect them and serve from a CDN or object storage.

### Collect Static Files

```bash
python manage.py collectstatic --no-input
```

This copies all static files to `STATIC_ROOT` (`staticfiles/` by default).

### Serving Options

**Option 1 — nginx (self-hosted):**

```nginx
server {
    location /static/ {
        alias /app/staticfiles/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://gunicorn;
    }
}
```

**Option 2 — AWS S3 + CloudFront:**

Install `django-storages`:

```bash
pip install django-storages[s3]
```

```python
# config/settings.py
DEFAULT_FILE_STORAGE  = 'storages.backends.s3boto3.S3Boto3Storage'
STATICFILES_STORAGE   = 'storages.backends.s3boto3.S3StaticStorage'
AWS_STORAGE_BUCKET_NAME = os.getenv('AWS_STORAGE_BUCKET_NAME')
AWS_S3_REGION_NAME      = os.getenv('AWS_S3_REGION_NAME', 'us-east-1')
STATIC_URL = f'https://{os.getenv("CDN_DOMAIN")}/static/'
```

**Option 3 — WhiteNoise (simple, no CDN required):**

```bash
pip install whitenoise
```

```python
# config/settings.py — insert after SecurityMiddleware
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # ← add here
    ...
]
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
```

---

## Logging and Monitoring

### Structured Logging

Configure JSON logging so log aggregators (Datadog, CloudWatch, Loki) can parse fields:

```bash
pip install python-json-logger
```

```python
# config/settings.py
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
    'loggers': {
        'django.request': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}
```

### Application Server (Gunicorn)

Run the app with [Gunicorn](https://gunicorn.org/):

```bash
pip install gunicorn
gunicorn config.wsgi:application \
    --workers 4 \
    --worker-class sync \
    --bind 0.0.0.0:8000 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
```

Worker count rule of thumb: `2 × CPU cores + 1`. For I/O-heavy workloads consider `--worker-class gevent`.

### Health Check Monitoring

The `/health` endpoint (no auth required) returns `{"status": "healthy", "database": "healthy"}`. Wire it into your load balancer health checks and uptime monitoring (e.g., UptimeRobot, AWS Route 53 health checks).

### Audit Log Cleanup

Schedule the cleanup command to run daily:

```cron
# crontab -e
0 2 * * * /app/venv/bin/python /app/manage.py cleanup_audit_logs >> /var/log/audit_cleanup.log 2>&1
```

---

## Backup and Disaster Recovery

### Database Backups

**Automated backups with `pg_dump`:**

```bash
#!/bin/bash
# backup.sh — run daily via cron
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="/backups/saas_prod_${TIMESTAMP}.dump"

pg_dump \
    --format=custom \
    --compress=9 \
    --file="${BACKUP_FILE}" \
    "${DATABASE_URL}"

# Upload to object storage (example: AWS S3)
aws s3 cp "${BACKUP_FILE}" "s3://my-backups/postgres/${TIMESTAMP}.dump"

# Remove local copy after upload
rm "${BACKUP_FILE}"
```

```cron
0 3 * * * /app/scripts/backup.sh >> /var/log/backup.log 2>&1
```

**Managed database backups:** AWS RDS, Neon, and Supabase all provide automated point-in-time recovery (PITR). Enable it and set a retention window of at least 7 days.

### Restore Procedure

```bash
# Restore from a custom-format dump
pg_restore \
    --clean \
    --if-exists \
    --dbname="${DATABASE_URL}" \
    /backups/saas_prod_20260101_030000.dump
```

After restoring, verify the schema is current:

```bash
python manage.py migrate --check
```

### Recovery Time Objectives

| Scenario                | Target RTO | Approach                                 |
| ----------------------- | ---------- | ---------------------------------------- |
| Single table corruption | < 1 hour   | Restore specific table from dump         |
| Full database loss      | < 4 hours  | Restore latest daily backup + WAL replay |
| Region failure          | < 8 hours  | Promote read replica in secondary region |

### Tenant Data Export

Before deleting a tenant, export their data for compliance:

```bash
python manage.py shell -c "
from tenants.models import Tenant
from widgets.models import Widget
import json

tenant_id = 'acme-corp'
data = {
    'widgets': list(Widget.objects.filter(tenant_id=tenant_id).values()),
}
print(json.dumps(data, indent=2, default=str))
" > acme-corp-export.json
```

---

## Docker Deployment

A minimal `Dockerfile` and `docker-compose.yml` for containerised deployments:

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --no-input

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]
```

```yaml
# docker-compose.yml
services:
  web:
    build: .
    env_file: .env.production
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
    command: >
      sh -c "python manage.py migrate --no-input &&
             gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 4"

  db:
    image: postgres:16
    environment:
      POSTGRES_DB: saas_prod
      POSTGRES_USER: saas_app
      POSTGRES_PASSWORD: "${DB_PASSWORD}"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U saas_app -d saas_prod"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

---

## Further Reading

- [`docs/developer-guide/configuration.md`](configuration.md) — full environment variable reference
- [`docs/developer-guide/migration.md`](migration.md) — database migration and upgrade procedures
- [`docs/adr/007-technology-stack.md`](../adr/007-technology-stack.md) — technology choices and rationale
- [`docs/adr/002-tenant-isolation-strategy.md`](../adr/002-tenant-isolation-strategy.md) — tenant isolation approach
