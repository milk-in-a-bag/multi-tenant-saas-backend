# Migration and Upgrade Guide

This guide covers database migration strategy, safe schema changes in a multi-tenant environment, and zero-downtime deployment procedures.

**Requirements: 20.1–20.9**

---

## Database Migration Strategy

This project uses [Django migrations](https://docs.djangoproject.com/en/5.0/topics/migrations/) to manage all schema changes. Every schema change must go through a migration file — never alter the database directly.

### Core Workflow

```bash
# 1. Edit your model in models.py
# 2. Generate the migration
python manage.py makemigrations <app_name>

# 3. Review the generated file in <app>/migrations/
# 4. Apply to your local database
python manage.py migrate

# 5. Commit both the model change and the migration file together
git add <app>/models.py <app>/migrations/
git commit -m "feat: add billing_email to Tenant"
```

### Migration Naming

Django auto-names migrations (`0003_auto_20260101_1200`). For clarity, supply a name:

```bash
python manage.py makemigrations tenants --name add_billing_email_to_tenant
```

### Checking Migration State

```bash
# Show all migrations and their applied status
python manage.py showmigrations

# Check if any unapplied migrations exist (exits non-zero if so)
python manage.py migrate --check
```

Use `migrate --check` in your CI pipeline to catch missing migrations before deployment.

---

## Safe Schema Migrations in a Multi-Tenant Environment

Because all tenant data lives in a single database, every schema change affects all tenants simultaneously. Follow these rules to avoid downtime or data loss.

### The Expand/Contract Pattern

Never make a breaking change in a single migration. Use the **expand/contract** pattern instead:

**Phase 1 — Expand (backwards-compatible, deploy first):**

- Add new nullable columns or tables.
- Add new indexes.
- Keep old columns and code paths working.

**Phase 2 — Migrate data (run after Phase 1 is deployed):**

- Backfill data into new columns.
- Verify data integrity.

**Phase 3 — Contract (deploy after data migration is complete):**

- Remove old columns or tables.
- Remove old code paths.
- Make new columns NOT NULL if required.

### Adding a New Column (Safe)

Adding a nullable column with a default is always safe — it does not lock the table:

```python
# migrations/0005_tenant_add_billing_email.py
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('tenants', '0004_previous')]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='billing_email',
            field=models.EmailField(blank=True, default=''),
        ),
    ]
```

To later make it NOT NULL, first backfill all rows, then alter the column in a separate migration:

```python
# migrations/0006_tenant_billing_email_not_null.py
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('tenants', '0005_tenant_add_billing_email')]

    operations = [
        # Only safe after all rows have been backfilled
        migrations.AlterField(
            model_name='tenant',
            name='billing_email',
            field=models.EmailField(blank=False),
        ),
    ]
```

### Renaming a Column (Requires Expand/Contract)

**Never rename a column in a single step** — the old column name disappears immediately, breaking any running instances that still reference it.

```python
# Step 1 — Add the new column (deploy this first)
migrations.AddField(model_name='tenant', name='company_name', field=models.CharField(max_length=255, default=''))

# Step 2 — Backfill: copy data from old column to new column
# (run as a data migration or management command)

# Step 3 — Remove the old column (deploy after all instances use new column)
migrations.RemoveField(model_name='tenant', name='name')
```

### Adding an Index (Safe, Non-Blocking)

Large tables can take minutes to index. Use `CONCURRENTLY` to avoid locking:

```python
from django.db import migrations, models
from django.contrib.postgres.operations import AddIndexConcurrently

class Migration(migrations.Migration):
    atomic = False  # Required for CONCURRENTLY

    operations = [
        AddIndexConcurrently(
            model_name='widget',
            index=models.Index(fields=['tenant', 'created_at'], name='idx_widgets_tenant_created'),
        ),
    ]
```

### Dropping a Column (Requires Two Deploys)

1. **Deploy 1**: Remove all code references to the column. The column still exists in the database.
2. **Deploy 2**: Run the `RemoveField` migration to drop the column.

This ensures no running instance tries to read a column that no longer exists.

---

## Data Migrations Across All Tenants

When you need to transform existing data (not just schema), use a Django data migration.

### Example: Backfilling a New Column

```python
# migrations/0007_backfill_billing_email.py
from django.db import migrations

def backfill_billing_email(apps, schema_editor):
    Tenant = apps.get_model('tenants', 'Tenant')
    # Process in batches to avoid locking the table for too long
    batch_size = 500
    qs = Tenant.objects.filter(billing_email='').only('id', 'admin_email')
    total = qs.count()
    for offset in range(0, total, batch_size):
        batch = qs[offset:offset + batch_size]
        for tenant in batch:
            tenant.billing_email = tenant.admin_email
        Tenant.objects.bulk_update(batch, ['billing_email'])

def reverse_backfill(apps, schema_editor):
    Tenant = apps.get_model('tenants', 'Tenant')
    Tenant.objects.update(billing_email='')

class Migration(migrations.Migration):
    dependencies = [('tenants', '0006_tenant_billing_email_not_null')]

    operations = [
        migrations.RunPython(backfill_billing_email, reverse_code=reverse_backfill),
    ]
```

### Key Rules for Data Migrations

- **Use `apps.get_model`** — never import models directly. The migration must use the historical model state.
- **Process in batches** — avoid loading all rows into memory at once.
- **Always provide `reverse_code`** — makes rollback possible.
- **Test on a copy of production data** before running on live.

---

## Backwards-Incompatible Changes

Some changes cannot be made backwards-compatibly. When they are unavoidable:

1. **Version the API** (see [API Versioning](#api-versioning-strategy) below).
2. **Communicate to tenants** in advance (see [`docs/developer-guide/tenant-communication.md`](tenant-communication.md)).
3. **Run both old and new code paths** during a transition window.
4. **Remove the old path** only after all clients have migrated.

Examples of backwards-incompatible changes:

- Removing a field from an API response.
- Changing a field type (e.g., `string` → `integer`).
- Changing authentication requirements on an endpoint.
- Renaming an endpoint URL.

---

## Zero-Downtime Deployment Strategies

### Blue/Green Deployment

Maintain two identical environments (blue = current, green = new). Switch traffic after green is verified:

1. Deploy new code to green environment.
2. Run `python manage.py migrate` on green.
3. Run smoke tests against green.
4. Switch load balancer to point to green.
5. Keep blue running for 15 minutes as a fallback.
6. Decommission blue.

**Requirement:** All migrations must be backwards-compatible (old code must work with new schema) so blue can still serve traffic while green is being validated.

### Rolling Deployment (Kubernetes / ECS)

For container orchestration platforms, rolling updates replace instances one at a time:

1. Run migrations as a pre-deploy job (not in the app container startup):

```yaml
# kubernetes/migrate-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: django-migrate
spec:
  template:
    spec:
      containers:
        - name: migrate
          image: myapp:v2
          command: ["python", "manage.py", "migrate", "--no-input"]
      restartPolicy: Never
```

2. Deploy the new app version. Old instances (running v1) and new instances (running v2) coexist briefly — both must work with the migrated schema.

### Pre-Deploy Checklist

- [ ] `python manage.py migrate --check` passes in CI.
- [ ] All new columns are nullable or have defaults.
- [ ] No column renames or drops in this deploy.
- [ ] Data migrations tested on a staging copy.
- [ ] Rollback plan documented.

---

## Testing Migrations in Staging

Always test migrations against a copy of production data before deploying to production.

### Restore Production Snapshot to Staging

```bash
# 1. Dump production (read-only replica recommended)
pg_dump --format=custom --file=prod_snapshot.dump "${PROD_DATABASE_URL}"

# 2. Restore to staging
pg_restore --clean --if-exists --dbname="${STAGING_DATABASE_URL}" prod_snapshot.dump

# 3. Apply pending migrations
DATABASE_URL="${STAGING_DATABASE_URL}" python manage.py migrate

# 4. Run the test suite against staging data
DATABASE_URL="${STAGING_DATABASE_URL}" pytest
```

### Automated Migration Testing in CI

Add a CI step that applies migrations to a fresh database on every pull request:

```yaml
# .github/workflows/ci.yml (example)
- name: Run migrations
  run: python manage.py migrate --no-input
  env:
    DATABASE_URL: postgresql://postgres:postgres@localhost:5432/test_db

- name: Check no pending migrations
  run: python manage.py migrate --check
```

---

## Rollback Procedures

### Rolling Back a Migration

Django supports reversing migrations if a `reverse_code` or reverse operation is defined:

```bash
# Roll back to a specific migration
python manage.py migrate tenants 0004_previous

# Roll back all migrations for an app
python manage.py migrate tenants zero
```

> **Warning:** Rolling back a migration that dropped a column is only possible if the column data still exists. Always test rollback in staging before production.

### Emergency Rollback Plan

For each deployment, document the rollback steps before deploying:

```
Deployment: v2.3.0
Migration: tenants 0007_backfill_billing_email

Rollback steps:
1. Switch load balancer back to v2.2.0 instances (blue/green) or roll back container image.
2. Run: python manage.py migrate tenants 0006_tenant_billing_email_not_null
3. Verify: python manage.py showmigrations
4. Smoke test: curl https://api.example.com/health
```

### When Rollback Is Not Possible

If a migration cannot be reversed (e.g., data was deleted), the rollback strategy is to restore from backup:

```bash
# Restore from the backup taken immediately before deployment
pg_restore --clean --if-exists --dbname="${DATABASE_URL}" /backups/pre_deploy_backup.dump
python manage.py migrate --check
```

Always take a database snapshot immediately before running migrations in production.

---

## API Versioning Strategy

The API is versioned via the URL path: `/api/v1/`, `/api/v2/`, etc.

### Adding a New API Version

1. Create a new URL prefix in `config/urls.py`:

```python
urlpatterns = [
    path('api/v1/', include('api.urls_v1')),
    path('api/v2/', include('api.urls_v2')),
]
```

2. Copy the existing URL conf and views to the new version module.
3. Make breaking changes only in the new version.
4. Keep the old version running for a deprecation window (minimum 6 months).

### Deprecation Policy

1. Announce deprecation in the API response headers: `Deprecation: true`, `Sunset: Sat, 01 Jan 2027 00:00:00 GMT`.
2. Document the migration path in the changelog and tenant communication.
3. Remove the old version after the sunset date.

```python
# In the deprecated view
response['Deprecation'] = 'true'
response['Sunset'] = 'Sat, 01 Jan 2027 00:00:00 GMT'
response['Link'] = '</api/v2/widgets/>; rel="successor-version"'
```

---

## Further Reading

- [`docs/developer-guide/deployment.md`](deployment.md) — production deployment and backup procedures
- [`docs/developer-guide/tenant-communication.md`](tenant-communication.md) — communicating changes to tenants
- [`docs/adr/008-database-schema-design.md`](../adr/008-database-schema-design.md) — schema design decisions
- [`docs/adr/002-tenant-isolation-strategy.md`](../adr/002-tenant-isolation-strategy.md) — tenant isolation approach
