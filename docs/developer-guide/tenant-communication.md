# Tenant Communication Guide

This guide covers how to communicate platform changes, maintenance windows, and API deprecations to tenant administrators.

**Requirements: 20.10**

---

## Overview

Tenant administrators rely on the platform being stable and predictable. Clear, timely communication about changes builds trust and reduces support burden. This guide provides templates and a deprecation policy to make that communication consistent.

---

## Maintenance Notifications

### Planned Maintenance

Send maintenance notifications at least **72 hours in advance** for routine maintenance and **2 weeks in advance** for major changes.

**Email template — planned maintenance:**

```
Subject: [Action Required] Scheduled Maintenance – {DATE} {TIME} UTC

Hello {TENANT_NAME} team,

We will be performing scheduled maintenance on {DATE} from {START_TIME} to {END_TIME} UTC.

What to expect:
- The API will be unavailable for approximately {DURATION}.
- All in-flight requests at the start of the window will be rejected with a 503 response.
- No data will be lost.

What you should do:
- Pause any automated jobs or integrations during this window.
- Resume normal operations after {END_TIME} UTC.

If you have questions or concerns, reply to this email or contact support at {SUPPORT_EMAIL}.

— The {PLATFORM_NAME} Team
```

### Emergency Maintenance

For unplanned outages or emergency patches, notify tenants as soon as the issue is identified:

```
Subject: [Urgent] Emergency Maintenance in Progress – {PLATFORM_NAME}

Hello {TENANT_NAME} team,

We are currently performing emergency maintenance to address {BRIEF_DESCRIPTION}.

Current status: {ONGOING / RESOLVED}
Started: {START_TIME} UTC
Estimated resolution: {ETA} UTC

Impact:
- {DESCRIBE_IMPACT, e.g., "API requests may return 503 errors."}

We will send a follow-up email when the issue is resolved.

— The {PLATFORM_NAME} Team
```

**Follow-up after resolution:**

```
Subject: [Resolved] Emergency Maintenance Complete – {PLATFORM_NAME}

Hello {TENANT_NAME} team,

The emergency maintenance that began at {START_TIME} UTC has been resolved as of {END_TIME} UTC.

Root cause: {BRIEF_EXPLANATION}
Duration: {DURATION}
Impact: {NUMBER} tenants experienced {DESCRIBE_IMPACT}

We apologize for the disruption. We have taken the following steps to prevent recurrence:
- {ACTION_1}
- {ACTION_2}

— The {PLATFORM_NAME} Team
```

---

## API Deprecation Policy

### Deprecation Timeline

| Phase        | Duration     | Actions                                                   |
| ------------ | ------------ | --------------------------------------------------------- |
| Announcement | Day 0        | Email all tenants; add `Deprecation` header to responses  |
| Soft sunset  | 0–6 months   | Old version still works; warnings in API responses        |
| Hard sunset  | 6 months     | Old version returns `410 Gone`; remove from documentation |
| Removal      | After sunset | Remove code and infrastructure                            |

The minimum deprecation window is **6 months** for any breaking change. For changes affecting authentication or core tenant operations, use a **12-month** window.

### Deprecation Headers

Add these headers to responses from deprecated endpoints:

```python
# In the deprecated view or middleware
def add_deprecation_headers(response, sunset_date: str, successor_url: str):
    """
    sunset_date: RFC 7231 date string, e.g. 'Sat, 01 Jan 2027 00:00:00 GMT'
    successor_url: URL of the replacement endpoint
    """
    response['Deprecation'] = 'true'
    response['Sunset'] = sunset_date
    response['Link'] = f'<{successor_url}>; rel="successor-version"'
    return response
```

Example usage in a view:

```python
class WidgetListViewV1(generics.ListCreateAPIView):
    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return add_deprecation_headers(
            response,
            sunset_date='Sat, 01 Jan 2027 00:00:00 GMT',
            successor_url='/api/v2/widgets/',
        )
```

### Deprecation Announcement Email

```
Subject: [Action Required] API v1 Deprecation – Migrate by {SUNSET_DATE}

Hello {TENANT_NAME} team,

We are deprecating version 1 of the {PLATFORM_NAME} API. Version 1 will stop working on {SUNSET_DATE}.

What is changing:
- {ENDPOINT_OR_FEATURE} is being replaced by {NEW_ENDPOINT_OR_FEATURE}.
- {DESCRIBE_BREAKING_CHANGE}

Migration guide:
{LINK_TO_MIGRATION_DOCS}

Timeline:
- Today: Deprecation warnings added to API responses (Deprecation and Sunset headers).
- {SOFT_SUNSET_DATE}: Deprecated endpoints will log warnings in your audit log.
- {SUNSET_DATE}: Deprecated endpoints will return 410 Gone.

What you need to do:
1. Review the migration guide at {LINK}.
2. Update your integration before {SUNSET_DATE}.
3. Test against the new endpoints in our staging environment at {STAGING_URL}.

If you need more time or have questions, contact us at {SUPPORT_EMAIL}.

— The {PLATFORM_NAME} Team
```

### Sunset Notification (30 Days Before)

```
Subject: [Reminder] API v1 Sunset in 30 Days – {PLATFORM_NAME}

Hello {TENANT_NAME} team,

This is a reminder that API v1 will stop working on {SUNSET_DATE} — 30 days from now.

If you are still using the deprecated endpoints, you must migrate before {SUNSET_DATE} to avoid service disruption.

Migration guide: {LINK_TO_MIGRATION_DOCS}
Support: {SUPPORT_EMAIL}

— The {PLATFORM_NAME} Team
```

---

## Changelog and Release Notes

Maintain a `CHANGELOG.md` at the repository root following [Keep a Changelog](https://keepachangelog.com/) format:

```markdown
# Changelog

## [Unreleased]

## [2.0.0] - 2026-06-01

### Breaking Changes

- `GET /api/v1/widgets/` is deprecated. Use `GET /api/v2/widgets/` instead.
- Widget `metadata` field now defaults to `{}` instead of `null`.

### Added

- API v2 with improved pagination (cursor-based).
- `billing_email` field on tenant registration.

### Fixed

- Rate limit counter now resets correctly at the top of the hour.

## [1.5.0] - 2026-03-01

### Added

- Audit log query endpoint with date range filtering.
```

Link to the changelog from your API documentation and tenant dashboard.

---

## In-App Notifications (Optional)

For platforms with a tenant dashboard, surface notifications via the audit log or a dedicated notifications endpoint:

```python
# core/audit_logger.py — log a platform announcement
AuditLogger.log_event(
    tenant_id=tenant_id,
    event_type='platform.announcement',
    details={
        'title': 'API v1 Deprecation',
        'message': 'API v1 will be sunset on 2027-01-01. See migration guide.',
        'link': 'https://docs.example.com/migration/v1-to-v2',
        'severity': 'warning',
    },
)
```

Tenants can retrieve these via `GET /api/tenants/audit-logs/` filtered by `event_type=platform.announcement`.

---

## Further Reading

- [`docs/developer-guide/migration.md`](migration.md) — database migration and API versioning strategy
- [`docs/developer-guide/deployment.md`](deployment.md) — deployment and maintenance procedures
