# ADR 003: Rate Limiting Implementation

**Date:** 2024-01-01  
**Status:** Accepted

---

## Context

The platform must protect shared infrastructure from abuse by any single tenant. Rate limits need to be enforced per tenant, reset on an hourly boundary, and vary by subscription tier. The implementation must be correct under concurrent requests (no race conditions that allow a tenant to exceed their limit) and must not introduce a hard dependency on an external service like Redis.

---

## Decision

Implement rate limiting using a `rate_limits` table in PostgreSQL. Each row tracks `(tenant_id, request_count, window_start)`. `RateLimitMiddleware` uses `SELECT FOR UPDATE` inside a database transaction to atomically read and increment the counter, preventing race conditions. The window resets when `NOW() >= window_start + 1 hour`.

Limits by subscription tier:

| Tier           | Requests / hour |
| -------------- | --------------- |
| `free`         | 100             |
| `professional` | 1,000           |
| `enterprise`   | 10,000          |

When the limit is exceeded the middleware returns `429 Too Many Requests` with a `Retry-After` header indicating seconds until the next window.

---

## Consequences

**Positive:**

- No additional infrastructure dependency — uses the existing PostgreSQL database
- `SELECT FOR UPDATE` guarantees correctness under concurrent load
- Tier-based limits are data-driven and can be changed without code deployment
- `Retry-After` header gives clients actionable information

**Negative / Trade-offs:**

- Every request incurs a database write to increment the counter — adds latency (~1–2 ms on a local database)
- Under very high request rates the `rate_limits` row becomes a hot spot; `SELECT FOR UPDATE` serialises updates for the same tenant
- A database outage would block rate limit checks; the middleware is designed to fail open (allow requests) if the DB is unreachable, which is a deliberate trade-off favouring availability

---

## Alternatives Considered

### Option A: Redis-based rate limiting (token bucket / sliding window)

Redis provides atomic `INCR` and `EXPIRE` operations ideal for rate limiting with sub-millisecond latency. Rejected for the starter kit because it adds an operational dependency (Redis cluster) that many developers forking the kit may not have. Documented as the recommended upgrade path for high-traffic deployments. See `docs/extension-points/rate-limiting-strategies.md`.

### Option B: In-memory rate limiting (per-process)

Track counters in Python dictionaries in each process. Zero latency but does not work correctly with multiple API server processes — each process has its own counter. Rejected as incorrect for any multi-process deployment.

### Option C: DRF built-in throttling

Django REST Framework includes `AnonRateThrottle` and `UserRateThrottle` backed by the Django cache framework. These are per-user rather than per-tenant and do not support tier-based limits without significant customisation. Rejected in favour of a purpose-built tenant-aware implementation.
