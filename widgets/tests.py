"""
Tests for Widget service and API endpoints
"""
import uuid
import pytest
from django.test import TestCase, RequestFactory
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError, NotFound

from .models import Widget
from .services import WidgetService
from .views import widget_list, widget_detail
from tenants.models import Tenant
from authentication.models import User
from core.middleware import set_current_tenant, clear_current_tenant


def make_tenant(suffix='a'):
    return Tenant.objects.create(
        id=f'tenant-{suffix}',
        subscription_tier='free',
        subscription_expiration=timezone.now() + timedelta(days=30),
        status='active',
    )


def make_user(tenant, role='admin', suffix=''):
    u = User.objects.create(
        tenant=tenant,
        username=f'user{suffix}-{tenant.id}',
        email=f'user{suffix}@{tenant.id}.com',
        role=role,
    )
    u.set_password('pass123')
    u.save()
    return u


@pytest.mark.django_db
class TestWidgetService(TestCase):
    """Unit tests for WidgetService CRUD operations"""

    def setUp(self):
        self.tenant = make_tenant('svc')
        self.user = make_user(self.tenant)
        set_current_tenant(self.tenant.id)

    def tearDown(self):
        clear_current_tenant()

    # --- create ---

    def test_create_widget_success(self):
        w = WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.user.id,
            name='My Widget',
            description='desc',
            metadata={'k': 'v'},
        )
        self.assertEqual(w.name, 'My Widget')
        self.assertEqual(w.tenant_id, self.tenant.id)
        self.assertEqual(w.created_by_id, self.user.id)
        self.assertEqual(w.metadata, {'k': 'v'})

    def test_create_widget_strips_whitespace(self):
        w = WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.user.id,
            name='  Padded  ',
        )
        self.assertEqual(w.name, 'Padded')

    def test_create_widget_blank_name_raises(self):
        with self.assertRaises(ValidationError):
            WidgetService.create_widget(
                tenant_id=self.tenant.id,
                user_id=self.user.id,
                name='   ',
            )

    def test_create_widget_duplicate_name_raises(self):
        WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.user.id,
            name='Dupe',
        )
        with self.assertRaises(ValidationError):
            WidgetService.create_widget(
                tenant_id=self.tenant.id,
                user_id=self.user.id,
                name='Dupe',
            )

    def test_create_widget_same_name_different_tenant_ok(self):
        other_tenant = make_tenant('other-svc')
        # Create user for other tenant in its own context
        set_current_tenant(other_tenant.id)
        other_user = make_user(other_tenant, suffix='o')
        set_current_tenant(self.tenant.id)
        WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.user.id,
            name='SharedName',
        )
        # Should not raise
        set_current_tenant(other_tenant.id)
        w2 = WidgetService.create_widget(
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            name='SharedName',
        )
        self.assertEqual(w2.name, 'SharedName')
        self.assertEqual(w2.tenant_id, other_tenant.id)

    # --- get ---

    def test_get_widget_success(self):
        w = WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.user.id,
            name='Fetch Me',
        )
        fetched = WidgetService.get_widget(self.tenant.id, w.id)
        self.assertEqual(fetched.id, w.id)

    def test_get_widget_wrong_tenant_raises(self):
        other_tenant = make_tenant('other-get')
        set_current_tenant(other_tenant.id)
        other_user = make_user(other_tenant, suffix='g')
        w = WidgetService.create_widget(
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            name='Other Widget',
        )
        set_current_tenant(self.tenant.id)
        with self.assertRaises(NotFound):
            WidgetService.get_widget(self.tenant.id, w.id)

    def test_get_widget_not_found_raises(self):
        with self.assertRaises(NotFound):
            WidgetService.get_widget(self.tenant.id, uuid.uuid4())

    # --- list ---

    def test_list_widgets_returns_only_tenant_widgets(self):
        WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.user.id,
            name='Widget A',
        )
        other_tenant = make_tenant('other-list')
        set_current_tenant(other_tenant.id)
        other_user = make_user(other_tenant, suffix='l')
        WidgetService.create_widget(
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            name='Widget B',
        )
        set_current_tenant(self.tenant.id)
        results = list(WidgetService.list_widgets(self.tenant.id))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, 'Widget A')

    def test_list_widgets_filter_name_contains(self):
        WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.user.id,
            name='Alpha Widget',
        )
        WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.user.id,
            name='Beta Gadget',
        )
        results = list(WidgetService.list_widgets(self.tenant.id, name_contains='Widget'))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, 'Alpha Widget')

    def test_list_widgets_empty_for_new_tenant(self):
        results = list(WidgetService.list_widgets(self.tenant.id))
        self.assertEqual(len(results), 0)

    # --- update ---

    def test_update_widget_name(self):
        w = WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.user.id,
            name='Old Name',
        )
        updated = WidgetService.update_widget(
            tenant_id=self.tenant.id,
            widget_id=w.id,
            name='New Name',
        )
        self.assertEqual(updated.name, 'New Name')

    def test_update_widget_metadata(self):
        w = WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.user.id,
            name='Meta Widget',
            metadata={'old': True},
        )
        updated = WidgetService.update_widget(
            tenant_id=self.tenant.id,
            widget_id=w.id,
            metadata={'new': True},
        )
        self.assertEqual(updated.metadata, {'new': True})

    def test_update_widget_wrong_tenant_raises(self):
        other_tenant = make_tenant('other-upd')
        set_current_tenant(other_tenant.id)
        other_user = make_user(other_tenant, suffix='u')
        w = WidgetService.create_widget(
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            name='Other Widget',
        )
        set_current_tenant(self.tenant.id)
        with self.assertRaises(NotFound):
            WidgetService.update_widget(
                tenant_id=self.tenant.id,
                widget_id=w.id,
                name='Hijacked',
            )

    # --- delete ---

    def test_delete_widget_success(self):
        w = WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.user.id,
            name='Delete Me',
        )
        WidgetService.delete_widget(self.tenant.id, w.id)
        with self.assertRaises(NotFound):
            WidgetService.get_widget(self.tenant.id, w.id)

    def test_delete_widget_wrong_tenant_raises(self):
        other_tenant = make_tenant('other-del')
        set_current_tenant(other_tenant.id)
        other_user = make_user(other_tenant, suffix='d')
        w = WidgetService.create_widget(
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            name='Other Widget',
        )
        set_current_tenant(self.tenant.id)
        with self.assertRaises(NotFound):
            WidgetService.delete_widget(self.tenant.id, w.id)


@pytest.mark.django_db
class TestWidgetAPIEndpoints(TestCase):
    """Integration tests for Widget API endpoints via APIClient"""

    def setUp(self):
        self.client = APIClient()
        self.tenant = make_tenant('api')
        self.admin = make_user(self.tenant, role='admin', suffix='adm')
        self.readonly = make_user(self.tenant, role='read_only', suffix='ro')
        set_current_tenant(self.tenant.id)

    def tearDown(self):
        clear_current_tenant()

    def _auth(self, user):
        from authentication.services import AuthService
        result = AuthService.authenticate_user(
            tenant_id=self.tenant.id,
            username=user.username,
            password='pass123',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {result['access_token']}")

    def test_list_widgets_authenticated(self):
        self._auth(self.admin)
        WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.admin.id,
            name='API Widget',
        )
        response = self.client.get('/api/widgets/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['count'], 1)

    def test_list_widgets_unauthenticated_returns_401(self):
        self.client.credentials()
        response = self.client.get('/api/widgets/')
        self.assertEqual(response.status_code, 401)

    def test_create_widget_admin(self):
        self._auth(self.admin)
        response = self.client.post('/api/widgets/', {'name': 'New Widget'}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['name'], 'New Widget')

    def test_create_widget_readonly_returns_403(self):
        self._auth(self.readonly)
        response = self.client.post('/api/widgets/', {'name': 'Forbidden'}, format='json')
        self.assertEqual(response.status_code, 403)

    def test_create_widget_missing_name_returns_400(self):
        self._auth(self.admin)
        response = self.client.post('/api/widgets/', {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_get_widget_detail(self):
        self._auth(self.admin)
        w = WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.admin.id,
            name='Detail Widget',
        )
        response = self.client.get(f'/api/widgets/{w.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Detail Widget')

    def test_update_widget_patch(self):
        self._auth(self.admin)
        w = WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.admin.id,
            name='Patch Me',
        )
        response = self.client.patch(
            f'/api/widgets/{w.id}/', {'name': 'Patched'}, format='json'
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['name'], 'Patched')

    def test_delete_widget(self):
        self._auth(self.admin)
        w = WidgetService.create_widget(
            tenant_id=self.tenant.id,
            user_id=self.admin.id,
            name='Delete Me',
        )
        response = self.client.delete(f'/api/widgets/{w.id}/')
        self.assertEqual(response.status_code, 204)

    def test_tenant_isolation_via_api(self):
        """Widget from another tenant should return 404"""
        other_tenant = make_tenant('api-other')
        set_current_tenant(other_tenant.id)
        other_user = make_user(other_tenant, suffix='oth')
        w = WidgetService.create_widget(
            tenant_id=other_tenant.id,
            user_id=other_user.id,
            name='Other Tenant Widget',
        )
        set_current_tenant(self.tenant.id)
        self._auth(self.admin)
        response = self.client.get(f'/api/widgets/{w.id}/')
        self.assertEqual(response.status_code, 404)

    def test_rate_limiting_applies_to_widget_endpoints(self):
        """Rate limiting middleware is wired up and applies to widget endpoints"""
        from core.middleware import RateLimitMiddleware
        from core.models import RateLimit
        # Verify the middleware is in the stack by checking settings
        from django.conf import settings
        middleware_list = settings.MIDDLEWARE
        self.assertIn('core.middleware.RateLimitMiddleware', middleware_list)
        self.assertIn('core.middleware.TenantContextMiddleware', middleware_list)
        # Verify RateLimitMiddleware comes after TenantContextMiddleware
        tenant_idx = middleware_list.index('core.middleware.TenantContextMiddleware')
        rate_idx = middleware_list.index('core.middleware.RateLimitMiddleware')
        self.assertGreater(rate_idx, tenant_idx)
