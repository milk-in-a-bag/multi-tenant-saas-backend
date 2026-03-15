# ADR 001: JWT Authentication

**Date:** 2024-01-01  
**Status:** Accepted

---

## Context

The system needs a mechanism to authenticate users across stateless HTTP requests. Each request must carry enough information to identify the tenant and user without requiring a database lookup on every call. The solution must support horizontal scaling (multiple API server instances) and integrate cleanly with Django REST Framework.

---

## Decision

Use JSON Web Tokens (JWT) via `djangorestframework-simplejwt` for user authentication. Access tokens are short-lived (1 hour) and embed `user_id`, `tenant_id`, and `role` as custom claims. Refresh tokens allow clients to obtain new access tokens without re-entering credentials.

---

## Consequences

**Positive:**

- Stateless — no session store or database lookup required to validate a token on each request
- Horizontally scalable — any API server instance can validate any token using the shared secret
- Self-contained — `tenant_id` and `role` claims eliminate extra DB queries in the hot path
- Standard — JWT is widely understood; client libraries exist for every platform
- `simplejwt` is actively maintained and integrates natively with DRF

**Negative / Trade-offs:**

- Tokens cannot be invalidated before expiry without a token blocklist (adds state)
- If the signing secret is compromised, all tokens are compromised until the secret is rotated
- 1-hour expiry means a compromised token is valid for up to 1 hour; mitigated by keeping access tokens short-lived and using refresh tokens for longevity

---

## Alternatives Considered

### Option A: Session-based authentication (Django sessions)

Django's built-in session middleware stores session data server-side (database or cache). This is simpler to invalidate but requires a shared session store across all API instances, adding operational complexity and a potential bottleneck. Rejected in favour of stateless JWT.

### Option B: Opaque tokens (database-backed)

Generate a random token, store it in the database, and look it up on every request. Simple to revoke but adds a DB round-trip to every authenticated request. Rejected due to performance and scaling concerns.

### Option C: OAuth 2.0 / OpenID Connect

A full OAuth 2.0 authorization server would be appropriate if the platform needs to support third-party application integrations or delegated access. For a starter kit where the platform itself is the identity provider, this adds significant complexity without proportional benefit. Marked as a future extension point.
