"""
Management command to generate sample tenants and demo data.

Usage:
    python manage.py seed_demo_data
    python manage.py seed_demo_data --reset   # Drop existing demo data first
    python manage.py seed_demo_data --quiet   # Suppress output

Creates three demo tenants:
  - acme-corp       (free tier)
  - globex-inc      (professional tier)
  - initech-llc     (enterprise tier)

Each tenant gets an admin user, a regular user, a read-only user,
sample widgets, and an API key for the admin.
"""

import hashlib
import secrets
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from authentication.models import APIKey, User
from core.middleware import clear_current_tenant, set_current_tenant
from tenants.models import Tenant
from widgets.models import Widget

# ---------------------------------------------------------------------------
# Demo data definitions
# ---------------------------------------------------------------------------

DEMO_TENANTS = [
    {
        "id": "acme-corp",
        "tier": "free",
        "users": [
            {"username": "alice", "email": "alice@acme-corp.example", "role": "admin", "password": "Demo1234!"},
            {"username": "bob", "email": "bob@acme-corp.example", "role": "user", "password": "Demo1234!"},
            {"username": "carol", "email": "carol@acme-corp.example", "role": "read_only", "password": "Demo1234!"},
        ],
        "widgets": [
            {
                "name": "Anvil",
                "description": "Classic heavy-duty anvil",
                "metadata": {"weight_kg": 50, "material": "iron"},
            },
            {
                "name": "Rocket Skates",
                "description": "High-speed locomotion device",
                "metadata": {"max_speed_kmh": 200},
            },
            {"name": "Giant Magnet", "description": "Attracts metallic objects", "metadata": {"strength_tesla": 5.0}},
        ],
    },
    {
        "id": "globex-inc",
        "tier": "professional",
        "users": [
            {"username": "hank", "email": "hank@globex-inc.example", "role": "admin", "password": "Demo1234!"},
            {"username": "luanne", "email": "luanne@globex-inc.example", "role": "user", "password": "Demo1234!"},
        ],
        "widgets": [
            {
                "name": "Doomsday Device",
                "description": "Proprietary energy source",
                "metadata": {"power_output_mw": 9999},
            },
            {"name": "Laser Array", "description": "Precision targeting system", "metadata": {"wavelength_nm": 532}},
        ],
    },
    {
        "id": "initech-llc",
        "tier": "enterprise",
        "users": [
            {"username": "bill", "email": "bill@initech-llc.example", "role": "admin", "password": "Demo1234!"},
            {"username": "peter", "email": "peter@initech-llc.example", "role": "user", "password": "Demo1234!"},
            {
                "username": "michael",
                "email": "michael@initech-llc.example",
                "role": "read_only",
                "password": "Demo1234!",
            },
        ],
        "widgets": [
            {
                "name": "TPS Report Cover",
                "description": "Standard cover sheet",
                "metadata": {"version": "v3.1", "color": "beige"},
            },
            {
                "name": "Red Stapler",
                "description": "Milton's stapler",
                "metadata": {"brand": "Swingline", "color": "red"},
            },
            {"name": "Flair Button", "description": "Minimum required flair", "metadata": {"count": 15}},
        ],
    },
]


class Command(BaseCommand):
    help = "Seed the database with demo tenants, users, and widgets"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Remove existing demo tenants before seeding",
        )
        parser.add_argument(
            "--quiet",
            action="store_true",
            help="Suppress informational output",
        )

    def handle(self, *args, **options):
        reset = options["reset"]
        quiet = options["quiet"]

        def log(msg, style=None):
            if not quiet:
                if style == "success":
                    self.stdout.write(self.style.SUCCESS(msg))
                elif style == "warning":
                    self.stdout.write(self.style.WARNING(msg))
                elif style == "error":
                    self.stdout.write(self.style.ERROR(msg))
                else:
                    self.stdout.write(msg)

        if not options.get("quiet"):
            from django.conf import settings

            if not settings.DEBUG:
                self.stderr.write(
                    self.style.ERROR(
                        "WARNING: seed_demo_data should not be run in production. "
                        "Set DEBUG=True or use a development environment."
                    )
                )
                return

        if reset:
            log("Removing existing demo tenants...", "warning")
            demo_ids = [t["id"] for t in DEMO_TENANTS]
            deleted_count, _ = Tenant.objects.filter(id__in=demo_ids).delete()
            log(f"  Removed {deleted_count} demo tenant(s) and all related data.", "warning")

        created_tenants = []

        for tenant_def in DEMO_TENANTS:
            tenant_id = tenant_def["id"]

            if Tenant.objects.filter(id=tenant_id).exists():
                log(f"  Skipping {tenant_id} (already exists). Use --reset to recreate.", "warning")
                continue

            try:
                with transaction.atomic():
                    set_current_tenant(tenant_id)

                    # Create tenant
                    Tenant.objects.create(
                        id=tenant_id,
                        subscription_tier=tenant_def["tier"],
                        subscription_expiration=timezone.now() + timedelta(days=365),
                        status="active",
                    )

                    # Create users
                    users_created = {}
                    for user_def in tenant_def["users"]:
                        user = User.objects.create_user(
                            tenant_id=tenant_id,
                            username=user_def["username"],
                            email=user_def["email"],
                            password=user_def["password"],
                            role=user_def["role"],
                        )
                        users_created[user_def["role"]] = user

                    # Create widgets (created by admin user)
                    admin_user = users_created.get("admin")
                    for widget_def in tenant_def["widgets"]:
                        Widget.objects.create(
                            tenant_id=tenant_id,
                            name=widget_def["name"],
                            description=widget_def.get("description"),
                            metadata=widget_def.get("metadata", {}),
                            created_by=admin_user,
                        )

                    # Generate an API key for the admin user
                    raw_key = secrets.token_urlsafe(32)
                    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
                    api_key_obj = APIKey.objects.create(
                        tenant_id=tenant_id,
                        user=admin_user,
                        key_hash=key_hash,
                    )

                    created_tenants.append(
                        {
                            "tenant_id": tenant_id,
                            "tier": tenant_def["tier"],
                            "admin_username": admin_user.username,
                            "admin_password": tenant_def["users"][0]["password"],
                            "api_key": raw_key,
                            "api_key_id": str(api_key_obj.id),
                            "widget_count": len(tenant_def["widgets"]),
                            "user_count": len(tenant_def["users"]),
                        }
                    )

            except Exception as exc:
                log(f"  ERROR creating {tenant_id}: {exc}", "error")
            finally:
                clear_current_tenant()

        if not created_tenants:
            log("No new demo tenants were created.", "warning")
            return

        log("", None)
        log("Demo data created successfully!", "success")
        log("=" * 60, None)

        for info in created_tenants:
            log("", None)
            log(f"Tenant: {info['tenant_id']}  [{info['tier']} tier]", None)
            log(f"  Users created : {info['user_count']}", None)
            log(f"  Widgets created: {info['widget_count']}", None)
            log("  Admin login:", None)
            log(f"    tenant_id : {info['tenant_id']}", None)
            log(f"    username  : {info['admin_username']}", None)
            log(f"    password  : {info['admin_password']}", None)
            log("  API Key (save this — shown once):", None)
            log(f"    {info['api_key']}", None)

        log("", None)
        log("=" * 60, None)
        log("To reset demo data: python manage.py seed_demo_data --reset", None)
        log("Swagger UI: http://localhost:8000/api/docs/", None)
