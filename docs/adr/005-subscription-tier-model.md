# ADR 005: Subscription Tier Model

**Date:** 2024-01-01  
**Status:** Accepted

---

## Context

The platform needs a subscription model that gates access to features and enforces resource limits. The model must be simple enough to understand and operate, flexible enough to customise for different SaaS products, and directly tied to the rate limiting system. New tenants must have a sensible default that does not require billing setup before they can evaluate the platform.

---

## Decision

Support three subscription tiers stored as a `VARCHAR` field on the `tenants` table:

| Tier           | Rate limit (req/hr) | Intended use                         |
| -------------- | ------------------- | ------------------------------------ |
| `free`         | 100                 | Evaluation, development, small usage |
| `professional` | 1,000               | Small to medium production workloads |
| `enterprise`   | 10,000              | High-volume production workloads     |

New tenants are assigned `free` by default. Each tier has a `subscription_expiration` date; when a paid subscription expires the tenant is automatically downgraded to `free` by the rate limiting middleware.

Tier names and limits are defined as constants in `tenants/models.py` and can be overridden via environment variables.

---

## Consequences

**Positive:**

- Three tiers cover the most common SaaS pricing structures (freemium + two paid tiers)
- Storing the tier as a string (not an integer) makes the database readable without a lookup table
- Automatic expiry downgrade prevents billing edge cases from causing service disruptions
- Tier limits are configurable without code changes

**Negative / Trade-offs:**

- Three fixed tiers may not fit every SaaS product — developers may need to add or rename tiers
- Feature flags beyond rate limits (e.g., enabling specific API endpoints per tier) require additional implementation; the starter kit only gates rate limits by tier
- Subscription management (payment processing, invoicing) is out of scope — this model only stores the tier and expiration date

---

## Alternatives Considered

### Option A: Two tiers (free / paid)

Simpler but less flexible. Most SaaS products benefit from a mid-tier option to capture customers who need more than free but less than enterprise pricing. Rejected in favour of three tiers.

### Option B: Fully configurable tiers (database-driven)

Store tier definitions in a separate table, allowing operators to create arbitrary tiers with custom limits. More flexible but significantly more complex to implement and operate. Appropriate for a mature platform; overkill for a starter kit. Documented as an extension point.

### Option C: Per-tenant custom limits only (no tiers)

Allow each tenant to have a unique rate limit with no concept of tiers. Flexible but removes the ability to offer standardised pricing plans. Rejected; custom per-tenant limits are supported as an override on top of tier-based defaults.
