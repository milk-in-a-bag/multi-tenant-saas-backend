"""
Management command to clean up tenants marked for deletion after 24 hours
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.data_isolator import DataIsolator
from core.middleware import clear_current_tenant, set_current_tenant
from core.models import AuditLog
from tenants.models import Tenant


class Command(BaseCommand):
    help = "Clean up tenants marked for deletion after 24 hours"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        # Find tenants pending deletion for more than 24 hours
        cutoff_time = timezone.now() - timedelta(hours=24)

        # Get tenants that have been pending deletion for more than 24 hours
        # We need to check the audit log for when deletion was requested
        pending_tenants = Tenant.objects.filter(status="pending_deletion")

        tenants_to_delete = []

        for tenant in pending_tenants:
            # Check when deletion was requested
            deletion_log = (
                AuditLog.objects.filter(tenant_id=tenant.id, event_type="tenant_deletion_requested")
                .order_by("-timestamp")
                .first()
            )

            if deletion_log and deletion_log.timestamp <= cutoff_time:
                tenants_to_delete.append(tenant)

        if not tenants_to_delete:
            self.stdout.write(self.style.SUCCESS("No tenants ready for deletion"))
            return

        self.stdout.write(f"Found {len(tenants_to_delete)} tenants ready for deletion:")

        for tenant in tenants_to_delete:
            self.stdout.write(f"  - {tenant.id} (status: {tenant.status})")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: No actual deletion performed"))
            return

        # Delete tenants and all their data
        deleted_count = 0

        for tenant in tenants_to_delete:
            try:
                with transaction.atomic():
                    # Set tenant context for final audit log
                    set_current_tenant(tenant.id)

                    # Log final deletion
                    AuditLog.objects.create(
                        tenant_id=tenant.id,
                        event_type="tenant_deleted",
                        details={"tenant_id": tenant.id, "deletion_completed_at": timezone.now().isoformat()},
                    )

                    # Clear tenant context before deletion
                    clear_current_tenant()

                    # Delete tenant (cascades to all related data)
                    DataIsolator.delete_tenant_data(tenant.id)

                    deleted_count += 1
                    self.stdout.write(self.style.SUCCESS(f"Deleted tenant: {tenant.id}"))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed to delete tenant {tenant.id}: {e}"))
            finally:
                clear_current_tenant()

        self.stdout.write(self.style.SUCCESS(f"Successfully deleted {deleted_count} tenants"))
