# ADR 008: Database Schema Design

**Date:** 2024-01-01  
**Status:** Accepted

---

## Context

The database schema must support multi-tenant data isolation, efficient querying within a tenant's data, cascading cleanup on tenant deletion, and Django's migration system. Key design decisions include the primary key strategy, the tenant identifier type, foreign key cascade behaviour, and the use of JSONB for flexible fields.

---

## Decision

**Primary keys:** UUIDs (`uuid4`) for all tenant-scoped tables (users, api_keys, audit_logs, widgets). The `tenants` table uses a human-readable slug (e.g., `acme-corp`) as its primary key to make logs and URLs readable.

**Tenant identifier:** `VARCHAR(255)` slug stored directly as the `tenant_id` foreign key on all tenant-scoped tables. This avoids a join to resolve the tenant on every query.

**Foreign key cascades:** All tenant-scoped tables declare `FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE`. Deleting a tenant row automatically removes all related data at the database level, providing a reliable cleanup guarantee independent of application code.

**JSONB fields:** `audit_logs.details` and `widgets.metadata` use PostgreSQL's `JSONB` type for flexible, schema-less data. This avoids adding columns for every possible audit event payload or widget attribute.

**Indexes:** Every tenant-scoped table has an index on `tenant_id`. Composite indexes cover the most common query patterns (e.g., `(tenant_id, email)` for user login, `(tenant_id, timestamp DESC)` for audit log pagination).

**Constraints:** `CHECK` constraints enforce valid values for `subscription_tier`, `status`, and `role` at the database level, providing a safety net independent of application validation.

---

## Consequences

**Positive:**

- `ON DELETE CASCADE` guarantees complete tenant data removal without application-level cleanup loops
- UUID primary keys avoid sequential ID enumeration attacks
- Human-readable tenant slugs make debugging and log analysis easier
- JSONB fields allow audit log and widget schemas to evolve without migrations
- Database-level `CHECK` constraints catch invalid data even if application validation is bypassed
- Composite indexes make the most common queries fast without over-indexing

**Negative / Trade-offs:**

- UUID primary keys are larger than integers and slightly slower for index lookups; acceptable for this workload
- Tenant slug as primary key means renaming a tenant requires updating all foreign keys (cascading update); tenant slugs are treated as immutable after creation
- JSONB fields are not strongly typed; invalid structures can be stored if application validation is bypassed
- `ON DELETE CASCADE` means a mistaken tenant deletion immediately removes all data; the `pending_deletion` soft-delete state provides a 24-hour grace period before the hard delete

---

## Alternatives Considered

### Option A: Integer auto-increment primary keys

Simpler and more compact than UUIDs. Rejected because sequential integer IDs are enumerable — an attacker who obtains one ID can guess adjacent IDs. UUIDs are unpredictable.

### Option B: Separate `tenant_id` lookup table (integer FK)

Store tenant IDs as integers and join to a `tenants` table on every query. Reduces storage for the FK column but adds a join to every tenant-scoped query. Rejected in favour of the slug FK which is self-documenting and avoids the join.

### Option C: Application-level cascade delete (no DB cascades)

Handle tenant data deletion entirely in application code, iterating over related tables. More explicit but fragile — a new table added without a corresponding delete step would leak data. Rejected in favour of database-level cascades which are enforced regardless of application code changes.

### Option D: EAV (Entity-Attribute-Value) for flexible fields

Use an EAV pattern instead of JSONB for `audit_logs.details` and `widgets.metadata`. EAV is notoriously difficult to query and maintain. Rejected in favour of JSONB which PostgreSQL handles natively and efficiently.
