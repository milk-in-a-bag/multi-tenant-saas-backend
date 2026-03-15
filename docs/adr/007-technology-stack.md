# ADR 007: Technology Stack

**Date:** 2026-03-15  
**Status:** Accepted

---

## Context

The starter kit needs a technology stack that is production-proven, well-documented, widely understood by backend developers, and has a rich ecosystem for the required capabilities (REST APIs, JWT auth, OpenAPI generation, property-based testing). The stack should minimise the number of moving parts while covering all requirements.

---

## Decision

| Component              | Choice                                               | Version |
| ---------------------- | ---------------------------------------------------- | ------- |
| Language               | Python                                               | 3.11+   |
| Web framework          | Django                                               | 5.x     |
| REST API layer         | Django REST Framework (DRF)                          | 3.x     |
| Database               | PostgreSQL                                           | 14+     |
| JWT authentication     | `djangorestframework-simplejwt`                      | latest  |
| OpenAPI generation     | `drf-spectacular`                                    | latest  |
| Property-based testing | `hypothesis`                                         | latest  |
| Test runner            | `pytest` + `pytest-django`                           | latest  |
| Password hashing       | `bcrypt` (via Django's `BCryptSHA256PasswordHasher`) | latest  |

---

## Consequences

**Positive:**

- Django + DRF is the most widely used Python web stack for REST APIs; large talent pool and extensive documentation
- PostgreSQL is the most capable open-source relational database; JSONB support is used for `audit_logs.details` and `widgets.metadata`
- `simplejwt` integrates natively with DRF's authentication classes; minimal boilerplate
- `drf-spectacular` generates accurate OpenAPI 3.0 specs from DRF viewsets with minimal annotation
- `hypothesis` is the leading property-based testing library for Python; well-suited for testing tenant isolation invariants
- All components are open-source with permissive licences (MIT / BSD)

**Negative / Trade-offs:**

- Django's synchronous ORM is not ideal for very high concurrency workloads; async Django (ASGI) is available but not used in this starter kit
- PostgreSQL is the only supported database; SQLite works for development but lacks `SELECT FOR UPDATE` semantics needed for rate limiting
- The stack is Python-only; teams using other languages would need to port the patterns

---

## Alternatives Considered

### Option A: FastAPI + SQLAlchemy

FastAPI offers native async support and automatic OpenAPI generation. SQLAlchemy is a more flexible ORM. Rejected because Django's batteries-included approach (admin, migrations, management commands, auth) reduces the amount of boilerplate in a starter kit. FastAPI is a better choice for pure async microservices.

### Option B: Node.js + Express + Prisma

Popular stack with a large ecosystem. Rejected because the team's expertise and the property-based testing requirement (`hypothesis` has no direct equivalent in the Node ecosystem) favour Python.

### Option C: MySQL / MariaDB instead of PostgreSQL

MySQL lacks native JSONB support (uses JSON with limited indexing) and has weaker support for `SELECT FOR UPDATE` in some configurations. PostgreSQL is the better choice for this workload. Rejected.
