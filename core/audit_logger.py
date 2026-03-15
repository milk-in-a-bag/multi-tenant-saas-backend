"""
Audit logging service for tracking security-relevant events
"""
from django.utils import timezone
from .models import AuditLog


class AuditLogger:
    """
    Service class for logging security-relevant events with tenant isolation.
    All log entries are associated with a tenant_id for proper data isolation.
    """

    @staticmethod
    def log_event(tenant_id, event_type, details, user_id=None, ip_address=None):
        """
        Log a generic audit event.

        Args:
            tenant_id: Tenant identifier (required)
            event_type: Type of event (e.g. 'authentication_success')
            details: Dict of event-specific details
            user_id: Optional user identifier
            ip_address: Optional client IP address
        """
        AuditLog.all_objects.create(
            tenant_id=tenant_id,
            event_type=event_type,
            user_id=user_id,
            details=details,
            ip_address=ip_address,
        )
        # EXTENSION_POINT: audit-log-processors
        # Add post-processing hooks here to forward audit events to external systems
        # (e.g., SIEM, Splunk, Datadog, SNS/SQS). Implement a processor as a callable
        # that accepts (tenant_id, event_type, details) and register it in settings.py
        # under AUDIT_LOG_PROCESSORS = ['myapp.processors.MyProcessor'].
        # See: docs/extension-points/audit-log-processors.md

    @staticmethod
    def log_authentication_success(tenant_id, user_id, username, ip_address=None):
        """Log a successful authentication event."""
        AuditLogger.log_event(
            tenant_id=tenant_id,
            event_type='authentication_success',
            user_id=user_id,
            details={'username': username, 'ip_address': ip_address},
            ip_address=ip_address,
        )

    @staticmethod
    def log_authentication_failure(tenant_id, username, reason='invalid_credentials', ip_address=None, user_id=None):
        """Log a failed authentication attempt."""
        AuditLogger.log_event(
            tenant_id=tenant_id,
            event_type='authentication_failed',
            user_id=user_id,
            details={'username': username, 'reason': reason, 'ip_address': ip_address},
            ip_address=ip_address,
        )

    @staticmethod
    def log_role_change(tenant_id, target_user_id, old_role, new_role, admin_user_id):
        """Log a user role change."""
        AuditLogger.log_event(
            tenant_id=tenant_id,
            event_type='role_changed',
            user_id=admin_user_id,
            details={
                'target_user_id': str(target_user_id),
                'old_role': old_role,
                'new_role': new_role,
                'changed_by': str(admin_user_id),
            },
        )

    @staticmethod
    def log_api_key_created(tenant_id, key_id, user_id, created_by):
        """Log API key creation."""
        AuditLogger.log_event(
            tenant_id=tenant_id,
            event_type='api_key_created',
            user_id=created_by,
            details={
                'key_id': str(key_id),
                'target_user_id': str(user_id),
                'created_by': str(created_by),
            },
        )

    @staticmethod
    def log_api_key_revoked(tenant_id, key_id, revoked_by):
        """Log API key revocation."""
        AuditLogger.log_event(
            tenant_id=tenant_id,
            event_type='api_key_revoked',
            user_id=revoked_by,
            details={
                'key_id': str(key_id),
                'revoked_by': str(revoked_by),
            },
        )

    @staticmethod
    def log_subscription_change(tenant_id, old_tier, new_tier, old_expiration, new_expiration):
        """Log a subscription tier change."""
        AuditLogger.log_event(
            tenant_id=tenant_id,
            event_type='subscription_updated',
            details={
                'old_tier': old_tier,
                'new_tier': new_tier,
                'old_expiration': old_expiration.isoformat() if old_expiration else None,
                'new_expiration': new_expiration.isoformat() if new_expiration else None,
            },
        )

    @staticmethod
    def log_tenant_deletion(tenant_id, admin_user_id):
        """Log a tenant deletion request."""
        AuditLogger.log_event(
            tenant_id=tenant_id,
            event_type='tenant_deletion_requested',
            user_id=admin_user_id,
            details={
                'tenant_id': tenant_id,
                'admin_user_id': str(admin_user_id),
                'status': 'pending_deletion',
                'timestamp': timezone.now().isoformat(),
            },
        )

    @staticmethod
    def get_logs(tenant_id, start_date=None, end_date=None, page=1, page_size=50):
        """
        Retrieve audit logs for a tenant with optional date range filtering and pagination.

        Args:
            tenant_id: Tenant identifier (enforces isolation)
            start_date: Optional start datetime filter
            end_date: Optional end datetime filter
            page: Page number (1-indexed)
            page_size: Number of results per page (max 200)

        Returns:
            dict: {
                'results': list of log dicts,
                'count': total matching records,
                'page': current page,
                'page_size': page size,
                'total_pages': total number of pages,
            }
        """
        page_size = min(page_size, 200)
        page = max(page, 1)

        qs = AuditLog.all_objects.filter(tenant_id=tenant_id).order_by('-timestamp')

        if start_date:
            qs = qs.filter(timestamp__gte=start_date)
        if end_date:
            qs = qs.filter(timestamp__lte=end_date)

        total = qs.count()
        offset = (page - 1) * page_size
        logs = qs[offset: offset + page_size]

        import math
        total_pages = math.ceil(total / page_size) if total > 0 else 1

        return {
            'results': [
                {
                    'id': str(log.id),
                    'tenant_id': log.tenant_id,
                    'event_type': log.event_type,
                    'user_id': str(log.user_id) if log.user_id else None,
                    'timestamp': log.timestamp.isoformat(),
                    'details': log.details,
                    'ip_address': log.ip_address,
                }
                for log in logs
            ],
            'count': total,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
        }
