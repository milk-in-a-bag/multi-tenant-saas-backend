# ADR 006: Audit Logging Approach

**Date:** 2026-03-15  
**Status:** Accepted

---

## Context

The platform must maintain an audit trail of security-relevant events (authentication, role changes, API key operations, subscription changes, tenant deletion) for compliance and incident response. Audit logs must be tenant-isolated (tenants can only query their own logs), retained for at least 90 days, and queryable by date range. The implementation must not significantly impact request latency.

---

## Decision

Write audit log entries synchronously to an `audit_logs` table in PostgreSQL. Each entry records:

- `tenant_id` — for isolation and filtering
- `event_type` — a string constant (e.g., `LOGIN_SUCCESS`, `API_KEY_REVOKED`)
- `user_id` — the actor (nullable for system events)
- `timestamp` — when the event occurred
- `details` — a JSONB field for event-specific data (old/new role, key ID, etc.)
- `ip_address` — the client IP for authentication events

A `cleanup_audit_logs` management command deletes entries older than 90 days (configurable via `AUDIT_LOG_RETENTION_DAYS`). The command is intended to be run as a scheduled task (cron or similar).

Audit logs are exposed to tenants via a paginated `GET /api/tenants/audit-logs/` endpoint, filtered by the authenticated tenant's `tenant_id`.

---

## Consequences

**Positive:**

- Synchronous writes ensure no audit events are lost due to queue failures
- JSONB `details` field accommodates varied event payloads without schema changes per event type
- Tenant isolation is enforced by the same `TenantManager` ORM filter used everywhere else
- Simple to query and export; no separate logging infrastructure required
- 90-day retention is configurable without code changes

**Negative / Trade-offs:**

- Synchronous writes add a small amount of latency to every audited operation (~1 ms)
- High event volume (e.g., many login attempts) can grow the table quickly; the retention cleanup must run regularly
- No real-time streaming of audit events to external SIEMs — documented as an extension point

---

## Alternatives Considered

### Option A: Asynchronous audit logging (message queue)

Write audit events to a queue (e.g., Celery + Redis) and process them asynchronously. Reduces request latency but risks losing events if the queue is unavailable or a worker crashes before processing. For a security audit log, losing events is unacceptable. Rejected in favour of synchronous writes.

### Option B: Structured logging to files / stdout

Write audit events as structured JSON log lines to stdout and rely on the deployment platform's log aggregation. Simple but makes tenant-scoped querying difficult without a log aggregation service. Rejected because the starter kit must work without external dependencies.

### Option C: Separate audit database

Store audit logs in a separate database for isolation and independent scaling. Adds operational complexity and a second database connection. Appropriate for high-compliance environments; documented as an extension point for operators who need it.
