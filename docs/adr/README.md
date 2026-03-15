# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for the multi-tenant SaaS backend. ADRs document significant design choices, the context that drove them, and the trade-offs accepted.

## What is an ADR?

An ADR is a short document capturing an important architectural decision. Each ADR records:

- **Context** — the forces and constraints that made the decision necessary
- **Decision** — what was decided
- **Consequences** — what becomes easier or harder as a result
- **Alternatives** — other options that were considered and why they were rejected

## Index

| ADR                                        | Title                        | Status   |
| ------------------------------------------ | ---------------------------- | -------- |
| [000](000-template.md)                     | Template                     | —        |
| [001](001-jwt-authentication.md)           | JWT Authentication           | Accepted |
| [002](002-tenant-isolation-strategy.md)    | Tenant Isolation Strategy    | Accepted |
| [003](003-rate-limiting-implementation.md) | Rate Limiting Implementation | Accepted |
| [004](004-api-key-hashing.md)              | API Key Hashing Strategy     | Accepted |
| [005](005-subscription-tier-model.md)      | Subscription Tier Model      | Accepted |
| [006](006-audit-logging-approach.md)       | Audit Logging Approach       | Accepted |
| [007](007-technology-stack.md)             | Technology Stack             | Accepted |
| [008](008-database-schema-design.md)       | Database Schema Design       | Accepted |

## Creating a New ADR

1. Copy `000-template.md` to `{NNN}-{short-title}.md`
2. Fill in all sections
3. Set status to `Accepted`
4. Add a row to the index table above
5. Link the ADR from relevant documentation sections
