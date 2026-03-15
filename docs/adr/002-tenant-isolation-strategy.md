# ADR 002: Tenant Isolation Strategy

**Date:** 2024-01-01  
**Status:** Accepted

---

## Context

The system must store data for multiple tenants while ensuring complete isolation — one tenant must never be able to read or write another tenant's data. Three common multi-tenancy models exist: separate databases per tenant, separate schemas per tenant (PostgreSQL), and a shared schema with a `tenant_id` discriminator column. The choice affects operational complexity, isolation strength, query performance, and migration difficulty.

---

## Decision

Use a **single database, shared schema** model with a `tenant_id` discriminator column on every tenant-scoped table. Isolation is enforced at three layers:

1. **Middleware** — `TenantContextMiddleware` extracts the tenant from the incoming credential and stores it in thread-local storage before any business logic runs.
2. **ORM** — `TenantManager.get_queryset()` automatically appends `WHERE tenant_id = <current_tenant>` to every Django queryset.
3. **Model** — `TenantIsolatedModel.save()` and `.delete()` validate that the object's `tenant_id` matches the current thread-local tenant.

---

## Consequences

**Positive:**

- Single database is simple to operate, back up, and restore
- Django migrations apply once and cover all tenants simultaneously
- Connection pooling is straightforward — one pool for the whole application
- Cross-tenant analytics (for platform operators) are possible with a single query
- The ORM-level filter means developers cannot accidentally omit tenant scoping

**Negative / Trade-offs:**

- A bug in the isolation layer could expose data across tenants — mitigated by three independent enforcement layers and property-based tests
- A noisy tenant can affect query performance for others — mitigated by rate limiting and database indexes on `tenant_id`
- Regulatory requirements (e.g., data residency) may require physical separation — this model does not support per-tenant database placement without significant rework

---

## Alternatives Considered

### Option A: Database-per-tenant

Each tenant gets its own PostgreSQL database. Provides the strongest isolation and supports per-tenant database placement. Rejected because it requires dynamic connection management, multiplies migration complexity by the number of tenants, and makes cross-tenant operations (billing, analytics) very difficult.

### Option B: Schema-per-tenant (PostgreSQL schemas)

Each tenant gets its own PostgreSQL schema within a shared database. Stronger isolation than shared schema, but Django's ORM does not natively support schema switching at runtime. Third-party packages (e.g., `django-tenants`) add complexity and constrain the ORM. Rejected in favour of the simpler shared-schema approach with disciplined query filtering.
