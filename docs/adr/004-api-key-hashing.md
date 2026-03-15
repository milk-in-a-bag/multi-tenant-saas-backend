# ADR 004: API Key Hashing Strategy

**Date:** 2026-03-15  
**Status:** Accepted

---

## Context

The platform supports API key authentication for programmatic access. API keys are long-lived credentials that must be stored securely. If the database is compromised, stored keys must not be usable by an attacker. The hashing strategy must balance security (resistance to brute-force) with lookup performance (every authenticated request hashes the incoming key and looks it up).

---

## Decision

Generate API keys as 32 bytes of cryptographically secure random data (`secrets.token_bytes(32)`), encoded as a 64-character hex string. Store only the **SHA-256 hash** of the key in the `api_keys.key_hash` column. The plaintext key is returned once at creation time and never stored.

On each authenticated request, the incoming key is SHA-256 hashed and looked up in the database:

```python
key_hash = hashlib.sha256(api_key.encode()).hexdigest()
APIKey.objects.get(key_hash=key_hash, revoked=False)
```

A unique index on `key_hash` makes this lookup O(log n).

---

## Consequences

**Positive:**

- A database breach does not expose usable API keys — an attacker would need to reverse SHA-256, which is computationally infeasible for a 32-byte random input
- SHA-256 is fast (~microseconds), adding negligible latency to each request
- The unique index on `key_hash` ensures fast lookups even with many keys
- Simple implementation with no external dependencies

**Negative / Trade-offs:**

- Unlike bcrypt, SHA-256 is not a password-hashing function — it has no salt and no work factor. This is acceptable here because the input is 32 bytes of cryptographically secure random data (256 bits of entropy), making dictionary attacks and rainbow tables useless. A brute-force attack against a 256-bit random value is computationally infeasible.
- If a key is lost by the user, it cannot be recovered — they must generate a new key. This is by design.
- API keys do not expire automatically; revocation is the only mechanism to invalidate them.

---

## Alternatives Considered

### Option A: bcrypt for API key hashing

bcrypt is the right choice for password hashing because passwords have low entropy and benefit from a high work factor. For a 32-byte random API key, bcrypt's work factor provides no additional security benefit (the entropy of the key already makes brute-force infeasible) but adds ~100 ms of latency to every API request. Rejected on performance grounds.

### Option B: Store plaintext API keys

Simple but catastrophic if the database is breached. Rejected unconditionally.

### Option C: HMAC with a server-side secret

HMAC-SHA256 with a server-side secret would mean that rotating the secret invalidates all existing keys. Adds operational complexity without meaningful security benefit over plain SHA-256 for high-entropy random inputs. Rejected in favour of simplicity.
