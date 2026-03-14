"""
Management command to delete audit logs older than the retention period (90 days).
Run periodically via cron or a task scheduler.

Usage:
    python manage.py cleanup_audit_logs
    python manage.py cleanup_audit_logs --days 30   # custom retention period
    python manage.py cleanup_audit_logs --dry-run   # preview without deleting
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from core.models import AuditLog


class Command(BaseCommand):
    help = 'Delete audit logs older than the retention period (default: 90 days)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=90,
            help='Retention period in days (default: 90)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview how many records would be deleted without actually deleting',
        )

    def handle(self, *args, **options):
        retention_days = options['days']
        dry_run = options['dry_run']

        cutoff = timezone.now() - timedelta(days=retention_days)

        # Use all_objects to bypass tenant filtering for system-level cleanup
        expired_qs = AuditLog.all_objects.filter(timestamp__lt=cutoff)
        count = expired_qs.count()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'[DRY RUN] Would delete {count} audit log(s) older than {retention_days} days '
                    f'(before {cutoff.isoformat()})'
                )
            )
            return

        deleted, _ = expired_qs.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f'Deleted {deleted} audit log(s) older than {retention_days} days '
                f'(before {cutoff.isoformat()})'
            )
        )
