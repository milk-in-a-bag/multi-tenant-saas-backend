"""
Unit tests for RateLimitMiddleware
"""

from datetime import timedelta

from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.middleware import RateLimitMiddleware, clear_current_tenant, set_current_tenant
from core.models import RateLimit
from tenants.models import Tenant


class RateLimitMiddlewareTest(TestCase):
    """Test rate limiting middleware functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.factory = RequestFactory()
        self.middleware = RateLimitMiddleware(get_response=lambda r: None)

        # Create test tenants with different tiers
        now = timezone.now()
        self.free_tenant = Tenant.objects.create(
            id="tenant-free", subscription_tier="free", subscription_expiration=now + timedelta(days=30)
        )
        self.pro_tenant = Tenant.objects.create(
            id="tenant-pro", subscription_tier="professional", subscription_expiration=now + timedelta(days=30)
        )
        self.enterprise_tenant = Tenant.objects.create(
            id="tenant-enterprise", subscription_tier="enterprise", subscription_expiration=now + timedelta(days=30)
        )
        self.expired_tenant = Tenant.objects.create(
            id="tenant-expired", subscription_tier="professional", subscription_expiration=now - timedelta(days=1)
        )

    def tearDown(self):
        """Clean up after tests"""
        clear_current_tenant()

    def test_public_endpoints_skip_rate_limiting(self):
        """Public endpoints should not be rate limited"""
        request = self.factory.get("/health")
        response = self.middleware.process_request(request)
        self.assertIsNone(response)

    def test_no_tenant_context_allows_request(self):
        """Requests without tenant context should proceed"""
        request = self.factory.get("/api/widgets")
        clear_current_tenant()
        response = self.middleware.process_request(request)
        self.assertIsNone(response)

    def test_free_tier_rate_limit(self):
        """Free tier should enforce 100 requests per hour"""
        request = self.factory.get("/api/widgets")
        set_current_tenant(self.free_tenant.id)

        # Make 100 requests - should all succeed
        for _ in range(100):
            response = self.middleware.process_request(request)
            self.assertIsNone(response)

        # 101st request should be rate limited
        response = self.middleware.process_request(request)
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)

    def test_professional_tier_rate_limit(self):
        """Professional tier should enforce 1000 requests per hour"""
        request = self.factory.get("/api/widgets")
        set_current_tenant(self.pro_tenant.id)

        # Make 1000 requests - should all succeed
        for _ in range(1000):
            response = self.middleware.process_request(request)
            self.assertIsNone(response)

        # 1001st request should be rate limited
        response = self.middleware.process_request(request)
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 429)

    def test_enterprise_tier_rate_limit(self):
        """Enterprise tier should enforce 10000 requests per hour"""
        request = self.factory.get("/api/widgets")
        set_current_tenant(self.enterprise_tenant.id)

        # Test a sample of requests (testing all 10000 would be slow)
        for _ in range(100):
            response = self.middleware.process_request(request)
            self.assertIsNone(response)

        # Verify the rate limit record shows correct count
        rate_limit = RateLimit.objects.get(tenant_id=self.enterprise_tenant.id)
        self.assertEqual(rate_limit.request_count, 100)

    def test_expired_subscription_uses_free_tier(self):
        """Expired subscriptions should downgrade to free tier limits"""
        request = self.factory.get("/api/widgets")
        set_current_tenant(self.expired_tenant.id)

        # Make 100 requests - should all succeed
        for _ in range(100):
            response = self.middleware.process_request(request)
            self.assertIsNone(response)

        # 101st request should be rate limited (free tier limit)
        response = self.middleware.process_request(request)
        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 429)

    def test_rate_limit_resets_hourly(self):
        """Rate limit counters should reset at the start of each hour"""
        request = self.factory.get("/api/widgets")
        set_current_tenant(self.free_tenant.id)

        # Make 100 requests to hit the limit
        for _ in range(100):
            self.middleware.process_request(request)

        # Verify we're at the limit
        response = self.middleware.process_request(request)
        self.assertEqual(response.status_code, 429)

        # Simulate moving to next hour by updating window_start
        rate_limit = RateLimit.objects.get(tenant_id=self.free_tenant.id)
        rate_limit.window_start = rate_limit.window_start - timedelta(hours=1)
        rate_limit.save()

        # Next request should succeed (counter reset)
        response = self.middleware.process_request(request)
        self.assertIsNone(response)

        # Verify counter was reset
        rate_limit.refresh_from_db()
        self.assertEqual(rate_limit.request_count, 1)

    def test_tenant_isolation_in_rate_limits(self):
        """Rate limits should be isolated per tenant"""
        request = self.factory.get("/api/widgets")

        # Tenant 1 makes 100 requests
        set_current_tenant(self.free_tenant.id)
        for _ in range(100):
            self.middleware.process_request(request)

        # Tenant 1 should be at limit
        response = self.middleware.process_request(request)
        self.assertEqual(response.status_code, 429)

        # Tenant 2 should still be able to make requests
        set_current_tenant(self.pro_tenant.id)
        response = self.middleware.process_request(request)
        self.assertIsNone(response)

    def test_retry_after_header(self):
        """429 response should include Retry-After header"""
        request = self.factory.get("/api/widgets")
        set_current_tenant(self.free_tenant.id)

        # Hit the rate limit
        for _ in range(100):
            self.middleware.process_request(request)

        response = self.middleware.process_request(request)
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response)

        # Retry-After should be a positive integer (seconds)
        retry_after = int(response["Retry-After"])
        self.assertGreater(retry_after, 0)
        self.assertLessEqual(retry_after, 3600)  # Max 1 hour
