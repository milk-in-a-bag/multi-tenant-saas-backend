"""
Property-based tests for tenant data isolation

Feature: multi-tenant-saas-backend
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.django import TestCase

from authentication.models import User
from core.middleware import clear_current_tenant, set_current_tenant
from core.models import AuditLog
from tenants.models import Tenant


# Custom strategies for generating test data
@st.composite
def tenant_id_strategy(draw):
    """Generate valid tenant identifiers"""
    prefix = draw(st.sampled_from(["tenant", "org", "company"]))
    suffix = draw(st.integers(min_value=1, max_value=999999))
    return f"{prefix}-{suffix}"


@st.composite
def tenant_with_data_strategy(draw):
    """Generate a tenant with associated audit log data"""
    tenant_id = draw(tenant_id_strategy())
    num_logs = draw(st.integers(min_value=1, max_value=10))

    return {
        "tenant_id": tenant_id,
        "subscription_tier": draw(st.sampled_from(["free", "professional", "enterprise"])),
        "num_logs": num_logs,
        "log_events": [
            {
                "event_type": draw(st.sampled_from(["user.login", "user.logout", "api_key.created", "role.changed"])),
                "details": {
                    "action": draw(
                        st.text(
                            alphabet=st.characters(min_codepoint=32, max_codepoint=126),  # ASCII printable only
                            min_size=1,
                            max_size=50,
                        )
                    )
                },
            }
            for _ in range(num_logs)
        ],
    }


@pytest.mark.django_db
class TestTenantDataIsolationProperties(TestCase):
    """
    Property-based tests for tenant data isolation
    """

    def setUp(self):
        """Set up test environment"""
        clear_current_tenant()

    def tearDown(self):
        """Clean up after tests"""
        clear_current_tenant()

    @settings(max_examples=20, deadline=None)
    @given(
        tenants_data=st.lists(tenant_with_data_strategy(), min_size=2, max_size=5, unique_by=lambda x: x["tenant_id"]),
        querying_tenant_index=st.integers(min_value=0, max_value=100),
    )
    def test_property_9_queries_return_only_tenant_data(self, tenants_data, querying_tenant_index):
        """
        **Property 9: Queries Return Only Tenant's Data**
        **Validates: Requirements 3.1, 3.3**

        For any tenant and any data query, the results should contain only data
        records where the tenant_id matches the authenticated tenant's identifier,
        and should not contain any records from other tenants.
        """
        # Setup: Create multiple tenants with data
        created_tenants = []
        all_tenant_ids = []

        for tenant_data in tenants_data:
            # Create tenant
            tenant = Tenant.objects.create(
                id=tenant_data["tenant_id"],
                subscription_tier=tenant_data["subscription_tier"],
                subscription_expiration=timezone.now() + timedelta(days=365),
                status="active",
            )
            created_tenants.append(tenant)
            all_tenant_ids.append(tenant.id)

            # Create a user for this tenant (needed for audit logs)
            user = User.objects.create(
                tenant=tenant,
                username=f"user_{tenant.id}",
                email=f"user@{tenant.id}.com",
                password="dummy_hash",
                role="user",
            )

            # Create audit logs for this tenant
            for log_event in tenant_data["log_events"]:
                AuditLog.objects.create(
                    tenant=tenant,
                    user=user,
                    event_type=log_event["event_type"],
                    details=log_event["details"],
                    ip_address="127.0.0.1",
                )

        # Select which tenant will be querying
        querying_tenant = created_tenants[querying_tenant_index % len(created_tenants)]
        querying_tenant_id = querying_tenant.id

        # Set tenant context to simulate authenticated request
        set_current_tenant(querying_tenant_id)

        try:
            # Execute: Query audit logs using TenantManager
            # This should automatically filter by tenant_id
            results = list(AuditLog.objects.all())

            # Assert: All results belong to the querying tenant
            for log in results:
                assert (
                    log.tenant_id == querying_tenant_id
                ), f"Found log with tenant_id {log.tenant_id} when querying as {querying_tenant_id}"

            # Assert: No results from other tenants are included
            other_tenant_ids = [tid for tid in all_tenant_ids if tid != querying_tenant_id]
            result_tenant_ids = [log.tenant_id for log in results]

            for other_tenant_id in other_tenant_ids:
                assert (
                    other_tenant_id not in result_tenant_ids
                ), f"Found data from tenant {other_tenant_id} when querying as {querying_tenant_id}"

            # Assert: Results count matches expected count for this tenant
            expected_count = next(t["num_logs"] for t in tenants_data if t["tenant_id"] == querying_tenant_id)
            assert len(results) == expected_count, (
                f"Expected {expected_count} logs for tenant {querying_tenant_id}, " f"but got {len(results)}"
            )

        finally:
            # Clean up tenant context
            clear_current_tenant()
