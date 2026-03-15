# Extension Point: Custom Audit Log Processors

**Requirement: 13.5**

This document explains how to add custom handling for audit log events beyond storing them in the database.

---

## Overview

All security-relevant events are written to the `audit_logs` table by `core/audit_logger.py`. The `AuditLogger` class provides static methods for each event type:

| Method                       | Event type stored           |
| ---------------------------- | --------------------------- |
| `log_authentication_success` | `authentication_success`    |
| `log_authentication_failure` | `authentication_failed`     |
| `log_role_change`            | `role_changed`              |
| `log_api_key_created`        | `api_key_created`           |
| `log_api_key_revoked`        | `api_key_revoked`           |
| `log_subscription_change`    | `subscription_updated`      |
| `log_tenant_deletion`        | `tenant_deletion_requested` |
| `log_event`                  | any custom event type       |

You can extend audit logging to:

- Forward events to an external SIEM (Splunk, Datadog, AWS CloudTrail)
- Send real-time alerts for high-severity events
- Write to a separate compliance database
- Publish events to a message queue (Celery, SQS, Kafka)

---

## Where to Make Changes

| File                   | What to change                                                   |
| ---------------------- | ---------------------------------------------------------------- |
| `core/audit_logger.py` | Add processor calls inside `log_event` or individual log methods |

---

## Extension Point Marker

```python
# EXTENSION_POINT: audit-log-processors
# Add custom audit event processors here.
# Processors run after the event is written to the database.
# Keep processors fast — use async tasks (Celery) for slow operations.
# See: docs/extension-points/audit-log-processors.md
```

This comment lives inside `AuditLogger.log_event` in `core/audit_logger.py`.

---

## Example 1: Forwarding Events to an External SIEM

Add a processor call at the end of `log_event`:

```python
# core/audit_logger.py

class AuditLogger:

    @staticmethod
    def log_event(tenant_id, event_type, details, user_id=None, ip_address=None):
        # Existing database write
        AuditLog.all_objects.create(
            tenant_id=tenant_id,
            event_type=event_type,
            user_id=user_id,
            details=details,
            ip_address=ip_address,
        )

        # EXTENSION_POINT: audit-log-processors
        # Forward to external processors after the DB write
        AuditLogger._run_processors(
            tenant_id=tenant_id,
            event_type=event_type,
            details=details,
            user_id=user_id,
            ip_address=ip_address,
        )

    @staticmethod
    def _run_processors(tenant_id, event_type, details, user_id, ip_address):
        """
        Call each registered processor. Failures are caught individually
        so one broken processor cannot block the others.
        """
        from core.audit_processors import AUDIT_PROCESSORS
        for processor in AUDIT_PROCESSORS:
            try:
                processor(
                    tenant_id=tenant_id,
                    event_type=event_type,
                    details=details,
                    user_id=user_id,
                    ip_address=ip_address,
                )
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(
                    "Audit processor %s failed: %s", processor.__name__, exc
                )
```

Create the processor registry:

```python
# core/audit_processors.py  (new file)

"""
Registry of custom audit log processors.
Add callables to AUDIT_PROCESSORS to run them on every audit event.
Each processor receives: tenant_id, event_type, details, user_id, ip_address
"""

AUDIT_PROCESSORS = []
```

---

## Example 2: Splunk HTTP Event Collector

```python
# core/audit_processors.py

import requests
from django.conf import settings
from django.utils import timezone


def splunk_processor(tenant_id, event_type, details, user_id, ip_address):
    """
    Forward audit events to Splunk via the HTTP Event Collector (HEC).
    Requires settings: SPLUNK_HEC_URL, SPLUNK_HEC_TOKEN
    """
    hec_url = getattr(settings, "SPLUNK_HEC_URL", None)
    hec_token = getattr(settings, "SPLUNK_HEC_TOKEN", None)
    if not hec_url or not hec_token:
        return

    payload = {
        "time": timezone.now().timestamp(),
        "sourcetype": "saas_audit",
        "event": {
            "tenant_id": tenant_id,
            "event_type": event_type,
            "user_id": str(user_id) if user_id else None,
            "ip_address": ip_address,
            "details": details,
        },
    }
    requests.post(
        hec_url,
        json=payload,
        headers={"Authorization": f"Splunk {hec_token}"},
        timeout=2,
    )


AUDIT_PROCESSORS = [splunk_processor]
```

---

## Example 3: Real-Time Alerts for High-Severity Events

```python
# core/audit_processors.py

from django.core.mail import send_mail
from django.conf import settings

HIGH_SEVERITY_EVENTS = {
    "authentication_failed",
    "tenant_deletion_requested",
    "api_key_revoked",
}


def alert_processor(tenant_id, event_type, details, user_id, ip_address):
    """
    Send an email alert for high-severity audit events.
    """
    if event_type not in HIGH_SEVERITY_EVENTS:
        return

    send_mail(
        subject=f"[ALERT] {event_type} — tenant {tenant_id}",
        message=(
            f"Event: {event_type}\n"
            f"Tenant: {tenant_id}\n"
            f"User: {user_id}\n"
            f"IP: {ip_address}\n"
            f"Details: {details}"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=getattr(settings, "SECURITY_ALERT_EMAILS", []),
        fail_silently=True,
    )


AUDIT_PROCESSORS = [alert_processor]
```

---

## Example 4: Async Processing with Celery

For slow processors (network calls, heavy processing), use a Celery task to avoid blocking the request:

```python
# core/tasks.py  (new file — requires Celery)

from celery import shared_task


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def forward_audit_event(self, tenant_id, event_type, details, user_id, ip_address):
    """
    Async task to forward audit events to external systems.
    Retries up to 3 times on failure.
    """
    try:
        import requests
        from django.conf import settings
        # ... forward to your SIEM ...
    except Exception as exc:
        raise self.retry(exc=exc)
```

```python
# core/audit_processors.py

from core.tasks import forward_audit_event


def async_siem_processor(tenant_id, event_type, details, user_id, ip_address):
    """Enqueue the event for async forwarding — returns immediately."""
    forward_audit_event.delay(
        tenant_id=tenant_id,
        event_type=event_type,
        details=details,
        user_id=str(user_id) if user_id else None,
        ip_address=ip_address,
    )


AUDIT_PROCESSORS = [async_siem_processor]
```

---

## Adding Custom Event Types

To log events from your own business logic, call `AuditLogger.log_event` directly:

```python
# your_app/services.py

from core.audit_logger import AuditLogger

AuditLogger.log_event(
    tenant_id=tenant_id,
    event_type="order_placed",          # your custom event type
    user_id=request.user.id,
    details={
        "order_id": str(order.id),
        "amount": str(order.total),
        "currency": order.currency,
    },
    ip_address=request.META.get("REMOTE_ADDR"),
)
```

All processors registered in `AUDIT_PROCESSORS` will automatically receive this event.

---

## Testing Custom Processors

```python
# core/tests/test_audit_processors.py

from django.test import TestCase
from unittest.mock import patch, MagicMock
from core.audit_logger import AuditLogger
from tenants.models import Tenant
from django.utils import timezone
from datetime import timedelta


class AuditProcessorTest(TestCase):
    def setUp(self):
        Tenant.objects.create(
            id="test-tenant",
            subscription_tier="free",
            subscription_expiration=timezone.now() + timedelta(days=365),
        )

    @patch("core.audit_processors.AUDIT_PROCESSORS", new_callable=list)
    def test_processor_is_called_on_log_event(self, mock_processors):
        mock_proc = MagicMock()
        mock_processors.append(mock_proc)

        AuditLogger.log_event(
            tenant_id="test-tenant",
            event_type="test_event",
            details={"key": "value"},
        )

        mock_proc.assert_called_once_with(
            tenant_id="test-tenant",
            event_type="test_event",
            details={"key": "value"},
            user_id=None,
            ip_address=None,
        )

    @patch("core.audit_processors.AUDIT_PROCESSORS", new_callable=list)
    def test_failing_processor_does_not_block_db_write(self, mock_processors):
        mock_processors.append(MagicMock(side_effect=Exception("processor error")))

        # Should not raise — the DB write must succeed even if the processor fails
        AuditLogger.log_event(
            tenant_id="test-tenant",
            event_type="test_event",
            details={},
        )

        from core.models import AuditLog
        self.assertTrue(
            AuditLog.all_objects.filter(
                tenant_id="test-tenant", event_type="test_event"
            ).exists()
        )
```

---

## Related Files

- `core/audit_logger.py` — `AuditLogger` class with all built-in log methods
- `core/models.py` — `AuditLog` model
- `tenants/services.py` — example of `AuditLogger` usage during tenant lifecycle events
- `authentication/services.py` — example of `AuditLogger` usage during authentication
