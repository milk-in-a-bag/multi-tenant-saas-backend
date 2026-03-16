"""
Management command to scaffold a new tenant-isolated resource following the Widget pattern.

Usage:
    python manage.py scaffold_resource <ResourceName>
    python manage.py scaffold_resource Product --fields price:decimal,active:boolean,quantity:integer
    python manage.py scaffold_resource Product --no-tests
"""

import os
import re

from django.core.management.base import BaseCommand, CommandError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESERVED_NAMES = {"core", "tenants", "authentication", "widgets", "api"}

FIELD_TYPE_MAP = {
    "string": "models.CharField(max_length=255, blank=True, default='')",
    "text": "models.TextField(blank=True, default='')",
    "integer": "models.IntegerField(default=0)",
    "decimal": "models.DecimalField(max_digits=10, decimal_places=2, default=0)",
    "boolean": "models.BooleanField(default=False)",
    "date": "models.DateField(null=True, blank=True)",
    "datetime": "models.DateTimeField(null=True, blank=True)",
    "json": "models.JSONField(default=dict, blank=True)",
}

SERIALIZER_FIELD_MAP = {
    "string": "serializers.CharField(required=False, allow_blank=True, default='')",
    "text": "serializers.CharField(required=False, allow_blank=True, default='')",
    "integer": "serializers.IntegerField(required=False, default=0)",
    "decimal": "serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=0)",
    "boolean": "serializers.BooleanField(required=False, default=False)",
    "date": "serializers.DateField(required=False, allow_null=True)",
    "datetime": "serializers.DateTimeField(required=False, allow_null=True)",
    "json": "serializers.JSONField(required=False, default=dict)",
}


# ---------------------------------------------------------------------------
# Template generators
# ---------------------------------------------------------------------------


def _gen_models(resource, snake, plural, fields):
    """Generate models.py content."""
    custom_fields = ""
    for fname, ftype in fields:
        custom_fields += f"    {fname} = {FIELD_TYPE_MAP[ftype]}\n"

    return f'''"""
{resource} model - tenant-isolated business entity
"""
import uuid
from django.db import models
from core.data_isolator import TenantIsolatedModel


class {resource}(TenantIsolatedModel):
    """
    Tenant-isolated {resource} entity.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        related_name='{plural}',
        db_column='tenant_id'
    )
    name = models.CharField(max_length=255)
{custom_fields}    created_by = models.ForeignKey(
        'authentication.User',
        on_delete=models.CASCADE,
        related_name='{plural}',
        db_column='created_by'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = '{plural}'
        unique_together = [('tenant', 'name')]
        indexes = [
            models.Index(fields=['tenant'], name='idx_{plural}_tenant'),
            models.Index(fields=['tenant', 'name'], name='idx_{plural}_name'),
            models.Index(fields=['tenant', '-created_at'], name='idx_{plural}_created_at'),
        ]

    def __str__(self):
        return f"{resource} '{{self.name}}' ({{self.tenant_id}})"
'''


def _gen_services(resource, snake, plural, fields):
    """Generate services.py content."""
    # Build extra kwargs for create
    extra_create_params = "".join(f", {fn}=None" for fn, _ in fields)
    extra_create_kwargs = "".join(f"\n                {fn}={fn}," for fn, _ in fields)
    # Build extra update logic
    extra_update_logic = ""
    for fn, _ in fields:
        extra_update_logic += f"""
        if {fn} is not None:
            {snake}.{fn} = {fn}
"""
    extra_update_params = "".join(f", {fn}=None" for fn, _ in fields)

    return f'''"""
{resource} service - tenant-isolated CRUD business logic.
"""
from django.db import IntegrityError
from rest_framework.exceptions import ValidationError, NotFound

from .models import {resource}


class {resource}Service:
    """
    Service class for {resource} CRUD operations.
    All methods enforce tenant isolation via the TenantIsolatedModel manager.
    """

    @staticmethod
    def create_{snake}(tenant_id, user_id, name{extra_create_params}):
        """Create a new {snake} for the given tenant."""
        if not name or not name.strip():
            raise ValidationError({{'name': 'This field is required.'}})

        try:
            {snake} = {resource}.objects.create(
                tenant_id=tenant_id,
                name=name.strip(),{extra_create_kwargs}
                created_by_id=user_id,
            )
        except IntegrityError:
            raise ValidationError(
                {{'name': f"A {snake} named '{{name}}' already exists in this tenant."}}
            )

        return {snake}

    @staticmethod
    def get_{snake}(tenant_id, {snake}_id):
        """Retrieve a single {snake} by ID, scoped to the tenant."""
        try:
            return {resource}.objects.get(id={snake}_id, tenant_id=tenant_id)
        except {resource}.DoesNotExist:
            raise NotFound({{'detail': '{resource} not found.'}})

    @staticmethod
    def list_{plural}(tenant_id, name_contains=None, created_after=None, created_before=None):
        """List all {plural} for the tenant with optional filters."""
        qs = {resource}.objects.filter(tenant_id=tenant_id).order_by('-created_at')

        if name_contains:
            qs = qs.filter(name__icontains=name_contains)
        if created_after:
            qs = qs.filter(created_at__gte=created_after)
        if created_before:
            qs = qs.filter(created_at__lte=created_before)

        return qs

    @staticmethod
    def update_{snake}(tenant_id, {snake}_id, name=None{extra_update_params}):
        """Update a {snake}, verifying it belongs to the tenant."""
        {snake} = {resource}Service.get_{snake}(tenant_id, {snake}_id)

        if name is not None:
            if not name.strip():
                raise ValidationError({{'name': 'Name cannot be blank.'}})
            {snake}.name = name.strip()
{extra_update_logic}
        try:
            {snake}.save()
        except IntegrityError:
            raise ValidationError(
                {{'name': f"A {snake} named '{{name}}' already exists in this tenant."}}
            )

        return {snake}

    @staticmethod
    def delete_{snake}(tenant_id, {snake}_id):
        """Delete a {snake}, verifying it belongs to the tenant."""
        {snake} = {resource}Service.get_{snake}(tenant_id, {snake}_id)
        {snake}.delete()
'''


def _gen_serializers(resource, snake, plural, fields):
    """Generate serializers.py content."""
    # Custom fields for create/update serializers
    custom_ser_fields = ""
    for fn, ft in fields:
        custom_ser_fields += f"    {fn} = {SERIALIZER_FIELD_MAP[ft]}\n"

    # ModelSerializer fields list
    model_fields_list = "['id', 'tenant_id', 'name'"
    for fn, _ in fields:
        model_fields_list += f", '{fn}'"
    model_fields_list += ", 'created_by', 'created_at', 'updated_at']"

    return f'''"""
{resource} serializers for input validation and response formatting
"""
from rest_framework import serializers
from .models import {resource}


class {resource}CreateSerializer(serializers.Serializer):
    """Validates input for {snake} creation"""
    name = serializers.CharField(max_length=255)
{custom_ser_fields}
    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError('Name cannot be blank.')
        return value.strip()


class {resource}UpdateSerializer(serializers.Serializer):
    """Validates input for {snake} updates (all fields optional)"""
    name = serializers.CharField(max_length=255, required=False)
{custom_ser_fields}
    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError('Name cannot be blank.')
        return value.strip()


class {resource}Serializer(serializers.ModelSerializer):
    """Response serializer for {resource} instances"""
    tenant_id = serializers.CharField()
    created_by = serializers.UUIDField(source='created_by_id')

    class Meta:
        model = {resource}
        fields = {model_fields_list}
        read_only_fields = fields


class {resource}FilterSerializer(serializers.Serializer):
    """Validates query parameters for {snake} list endpoint"""
    name_contains = serializers.CharField(required=False)
    created_after = serializers.DateTimeField(required=False)
    created_before = serializers.DateTimeField(required=False)
    page = serializers.IntegerField(required=False, default=1, min_value=1)
    page_size = serializers.IntegerField(required=False, default=20, min_value=1, max_value=100)

    def validate(self, data):
        after = data.get('created_after')
        before = data.get('created_before')
        if after and before and after > before:
            raise serializers.ValidationError('created_after must be before created_before.')
        return data
'''


def _gen_views(resource, snake, plural, fields):
    """Generate views.py content."""
    # Build extra kwargs for create call
    extra_create_kwargs = "".join(f"\n        {fn}=data.get('{fn}')," for fn, _ in fields)
    # Build extra kwargs for update call
    extra_update_kwargs = "".join(f"\n            {fn}=data.get('{fn}')," for fn, _ in fields)

    return f'''"""
{resource} API views - tenant-isolated CRUD endpoints
"""
from drf_spectacular.utils import (
    extend_schema,
    OpenApiResponse,
    OpenApiParameter,
    inline_serializer,
)
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .services import {resource}Service
from .serializers import (
    {resource}CreateSerializer,
    {resource}UpdateSerializer,
    {resource}Serializer,
    {resource}FilterSerializer,
)
from core.middleware import get_current_tenant

_ErrorSerializer = inline_serializer(
    name='{resource}Error',
    fields={{
        'error': inline_serializer(
            name='{resource}ErrorDetail',
            fields={{
                'code': serializers.CharField(),
                'message': serializers.CharField(),
                'details': serializers.DictField(child=serializers.CharField()),
            }},
        )
    }},
)

_{resource}PageSerializer = inline_serializer(
    name='{resource}Page',
    fields={{
        'count': serializers.IntegerField(),
        'page': serializers.IntegerField(),
        'page_size': serializers.IntegerField(),
        'results': {resource}Serializer(many=True),
    }},
)

_RATE_LIMIT_NOTE = (
    '\\n\\n**Rate limiting:** Counts against the tenant hourly quota '
    '(100/1000/10000 req/hr for free/professional/enterprise). '
    'Returns 429 with Retry-After when exceeded.'
)

_TENANT_ISOLATION_NOTE = (
    '\\n\\n**Tenant isolation:** Only {plural} belonging to the authenticated tenant '
    'are visible or modifiable. Cross-tenant access is rejected.'
)


def _paginate(queryset, page, page_size):
    """Simple offset-based pagination helper."""
    total = queryset.count()
    offset = (page - 1) * page_size
    items = queryset[offset: offset + page_size]
    return {{'count': total, 'page': page, 'page_size': page_size, 'results': items}}


@extend_schema(
    tags=['{plural}'],
    summary='List {plural}',
    description=(
        'Return a paginated list of {plural} for the authenticated tenant.'
        + _TENANT_ISOLATION_NOTE
        + _RATE_LIMIT_NOTE
    ),
    parameters=[
        OpenApiParameter('name_contains', str, OpenApiParameter.QUERY, required=False),
        OpenApiParameter('created_after', str, OpenApiParameter.QUERY, required=False),
        OpenApiParameter('created_before', str, OpenApiParameter.QUERY, required=False),
        OpenApiParameter('page', int, OpenApiParameter.QUERY, required=False),
        OpenApiParameter('page_size', int, OpenApiParameter.QUERY, required=False),
    ],
    responses={{
        200: OpenApiResponse(response=_{resource}PageSerializer, description='Paginated {snake} list'),
        400: OpenApiResponse(response=_ErrorSerializer, description='Invalid query parameters'),
        401: OpenApiResponse(response=_ErrorSerializer, description='Not authenticated'),
        429: OpenApiResponse(description='Rate limit exceeded'),
    }},
    methods=['GET'],
)
@extend_schema(
    tags=['{plural}'],
    summary='Create {snake}',
    description=(
        'Create a new {snake} for the authenticated tenant. '
        '{resource} names must be unique within a tenant. '
        'Requires admin or user role.'
        + _TENANT_ISOLATION_NOTE
        + _RATE_LIMIT_NOTE
    ),
    request={resource}CreateSerializer,
    responses={{
        201: OpenApiResponse(response={resource}Serializer, description='{resource} created'),
        400: OpenApiResponse(response=_ErrorSerializer, description='Validation error or duplicate name'),
        401: OpenApiResponse(response=_ErrorSerializer, description='Not authenticated'),
        403: OpenApiResponse(response=_ErrorSerializer, description='Admin or user role required'),
        429: OpenApiResponse(description='Rate limit exceeded'),
    }},
    methods=['POST'],
)
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def {snake}_list(request):
    """
    GET  /api/{plural}/   - List {plural} for the current tenant
    POST /api/{plural}/   - Create a new {snake} (admin and user roles)
    """
    tenant_id = get_current_tenant()
    if not tenant_id:
        return Response({{'error': 'Tenant context required'}}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        filter_serializer = {resource}FilterSerializer(data=request.query_params)
        if not filter_serializer.is_valid():
            return Response(filter_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        params = filter_serializer.validated_data
        qs = {resource}Service.list_{plural}(
            tenant_id=tenant_id,
            name_contains=params.get('name_contains'),
            created_after=params.get('created_after'),
            created_before=params.get('created_before'),
        )
        page_data = _paginate(qs, params['page'], params['page_size'])
        page_data['results'] = {resource}Serializer(page_data['results'], many=True).data
        return Response(page_data, status=status.HTTP_200_OK)

    if request.user.role not in ('admin', 'user'):
        return Response(
            {{'error': 'Admin or user role required to create {plural}'}},
            status=status.HTTP_403_FORBIDDEN,
        )

    serializer = {resource}CreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    {snake} = {resource}Service.create_{snake}(
        tenant_id=tenant_id,
        user_id=request.user.id,
        name=data['name'],{extra_create_kwargs}
    )
    return Response({resource}Serializer({snake}).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=['{plural}'],
    summary='Get {snake}',
    description=(
        'Retrieve a single {snake} by ID.'
        + _TENANT_ISOLATION_NOTE
        + _RATE_LIMIT_NOTE
    ),
    responses={{
        200: OpenApiResponse(response={resource}Serializer, description='{resource} details'),
        401: OpenApiResponse(response=_ErrorSerializer, description='Not authenticated'),
        404: OpenApiResponse(response=_ErrorSerializer, description='{resource} not found'),
        429: OpenApiResponse(description='Rate limit exceeded'),
    }},
    methods=['GET'],
)
@extend_schema(
    tags=['{plural}'],
    summary='Update {snake}',
    description=(
        'Fully replace a {snake}. Requires admin or user role.'
        + _TENANT_ISOLATION_NOTE
        + _RATE_LIMIT_NOTE
    ),
    request={resource}UpdateSerializer,
    responses={{
        200: OpenApiResponse(response={resource}Serializer, description='Updated {snake}'),
        400: OpenApiResponse(response=_ErrorSerializer, description='Validation error'),
        401: OpenApiResponse(response=_ErrorSerializer, description='Not authenticated'),
        403: OpenApiResponse(response=_ErrorSerializer, description='Admin or user role required'),
        404: OpenApiResponse(response=_ErrorSerializer, description='{resource} not found'),
        429: OpenApiResponse(description='Rate limit exceeded'),
    }},
    methods=['PUT'],
)
@extend_schema(
    tags=['{plural}'],
    summary='Partially update {snake}',
    description=(
        'Update one or more {snake} fields. Requires admin or user role.'
        + _TENANT_ISOLATION_NOTE
        + _RATE_LIMIT_NOTE
    ),
    request={resource}UpdateSerializer,
    responses={{
        200: OpenApiResponse(response={resource}Serializer, description='Updated {snake}'),
        400: OpenApiResponse(response=_ErrorSerializer, description='Validation error'),
        401: OpenApiResponse(response=_ErrorSerializer, description='Not authenticated'),
        403: OpenApiResponse(response=_ErrorSerializer, description='Admin or user role required'),
        404: OpenApiResponse(response=_ErrorSerializer, description='{resource} not found'),
        429: OpenApiResponse(description='Rate limit exceeded'),
    }},
    methods=['PATCH'],
)
@extend_schema(
    tags=['{plural}'],
    summary='Delete {snake}',
    description=(
        'Permanently delete a {snake}. Requires admin or user role.'
        + _TENANT_ISOLATION_NOTE
        + _RATE_LIMIT_NOTE
    ),
    responses={{
        204: OpenApiResponse(description='{resource} deleted'),
        401: OpenApiResponse(response=_ErrorSerializer, description='Not authenticated'),
        403: OpenApiResponse(response=_ErrorSerializer, description='Admin or user role required'),
        404: OpenApiResponse(response=_ErrorSerializer, description='{resource} not found'),
        429: OpenApiResponse(description='Rate limit exceeded'),
    }},
    methods=['DELETE'],
)
@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def {snake}_detail(request, {snake}_id):
    """
    GET    /api/{plural}/<id>/  - Retrieve a {snake}
    PUT    /api/{plural}/<id>/  - Full update (admin and user roles)
    PATCH  /api/{plural}/<id>/  - Partial update (admin and user roles)
    DELETE /api/{plural}/<id>/  - Delete a {snake} (admin and user roles)
    """
    tenant_id = get_current_tenant()
    if not tenant_id:
        return Response({{'error': 'Tenant context required'}}, status=status.HTTP_400_BAD_REQUEST)

    if request.method == 'GET':
        {snake} = {resource}Service.get_{snake}(tenant_id, {snake}_id)
        return Response({resource}Serializer({snake}).data, status=status.HTTP_200_OK)

    if request.user.role not in ('admin', 'user'):
        return Response(
            {{'error': 'Admin or user role required for this operation'}},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method in ('PUT', 'PATCH'):
        serializer = {resource}UpdateSerializer(data=request.data, partial=(request.method == 'PATCH'))
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        {snake} = {resource}Service.update_{snake}(
            tenant_id=tenant_id,
            {snake}_id={snake}_id,
            name=data.get('name'),{extra_update_kwargs}
        )
        return Response({resource}Serializer({snake}).data, status=status.HTTP_200_OK)

    {resource}Service.delete_{snake}(tenant_id, {snake}_id)
    return Response(status=status.HTTP_204_NO_CONTENT)
'''


def _gen_urls(resource, snake, plural):
    """Generate urls.py content."""
    return f'''"""
URL patterns for {resource} API
"""
from django.urls import path
from . import views

urlpatterns = [
    path('', views.{snake}_list, name='{snake}-list'),
    path('<uuid:{snake}_id>/', views.{snake}_detail, name='{snake}-detail'),
]
'''


def _gen_apps(resource, snake):
    """Generate apps.py content."""
    return f"""from django.apps import AppConfig


class {resource}Config(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = '{snake}'
"""


def _gen_test_service(resource, snake, plural, fields):
    """Generate tests/test_{snake}_service.py content."""
    extra_create_kwargs = "".join(f"\n            {fn}=None," for fn, _ in fields)
    return f'''"""
Unit tests for {resource}Service
"""
from django.test import TestCase
from unittest.mock import patch

from {snake}.models import {resource}
from {snake}.services import {resource}Service


class {resource}ServiceTestCase(TestCase):
    """Unit tests for {resource}Service CRUD operations."""

    def setUp(self):
        """Set up test tenant and user."""
        import uuid
        from tenants.models import Tenant
        from authentication.models import User
        from django.utils import timezone
        from datetime import timedelta

        self.tenant = Tenant.objects.create(
            id=str(uuid.uuid4()),
            subscription_tier='free',
            subscription_expiration=timezone.now() + timedelta(days=30),
        )
        self.user = User.objects.create_user(
            tenant=self.tenant,
            username='testuser',
            email='test@example.com',
            password='testpass123',
            role='admin',
        )

    def test_create_{snake}(self):
        """Test creating a {snake} succeeds with valid data."""
        with patch('core.middleware.get_current_tenant', return_value=self.tenant.id):
            {snake} = {resource}Service.create_{snake}(
                tenant_id=self.tenant.id,
                user_id=self.user.id,
                name='Test {resource}',{extra_create_kwargs}
            )
        self.assertEqual({snake}.name, 'Test {resource}')
        self.assertEqual(str({snake}.tenant_id), str(self.tenant.id))

    def test_create_{snake}_duplicate_name_raises(self):
        """Test that duplicate {snake} names within a tenant raise ValidationError."""
        from rest_framework.exceptions import ValidationError
        with patch('core.middleware.get_current_tenant', return_value=self.tenant.id):
            {resource}Service.create_{snake}(
                tenant_id=self.tenant.id,
                user_id=self.user.id,
                name='Duplicate',
            )
            with self.assertRaises(ValidationError):
                {resource}Service.create_{snake}(
                    tenant_id=self.tenant.id,
                    user_id=self.user.id,
                    name='Duplicate',
                )

    def test_get_{snake}(self):
        """Test retrieving a {snake} by ID."""
        with patch('core.middleware.get_current_tenant', return_value=self.tenant.id):
            created = {resource}Service.create_{snake}(
                tenant_id=self.tenant.id,
                user_id=self.user.id,
                name='Get Test',
            )
            fetched = {resource}Service.get_{snake}(self.tenant.id, created.id)
        self.assertEqual(fetched.id, created.id)

    def test_list_{plural}(self):
        """Test listing {plural} returns only tenant's data."""
        with patch('core.middleware.get_current_tenant', return_value=self.tenant.id):
            {resource}Service.create_{snake}(self.tenant.id, self.user.id, 'Item 1')
            {resource}Service.create_{snake}(self.tenant.id, self.user.id, 'Item 2')
            results = {resource}Service.list_{plural}(self.tenant.id)
        self.assertEqual(results.count(), 2)

    def test_update_{snake}(self):
        """Test updating a {snake}."""
        with patch('core.middleware.get_current_tenant', return_value=self.tenant.id):
            {snake} = {resource}Service.create_{snake}(self.tenant.id, self.user.id, 'Original')
            updated = {resource}Service.update_{snake}(self.tenant.id, {snake}.id, name='Updated')
        self.assertEqual(updated.name, 'Updated')

    def test_delete_{snake}(self):
        """Test deleting a {snake}."""
        from rest_framework.exceptions import NotFound
        with patch('core.middleware.get_current_tenant', return_value=self.tenant.id):
            {snake} = {resource}Service.create_{snake}(self.tenant.id, self.user.id, 'To Delete')
            {resource}Service.delete_{snake}(self.tenant.id, {snake}.id)
            with self.assertRaises(NotFound):
                {resource}Service.get_{snake}(self.tenant.id, {snake}.id)

    def test_tenant_isolation(self):
        """Test that {plural} from another tenant are not accessible."""
        import uuid
        from tenants.models import Tenant
        from authentication.models import User
        from django.utils import timezone
        from datetime import timedelta
        from rest_framework.exceptions import NotFound

        other_tenant = Tenant.objects.create(
            id=str(uuid.uuid4()),
            subscription_tier='free',
            subscription_expiration=timezone.now() + timedelta(days=30),
        )
        other_user = User.objects.create_user(
            tenant=other_tenant,
            username='otheruser',
            email='other@example.com',
            password='testpass123',
            role='admin',
        )
        with patch('core.middleware.get_current_tenant', return_value=other_tenant.id):
            {snake} = {resource}Service.create_{snake}(other_tenant.id, other_user.id, 'Other Tenant Item')

        with self.assertRaises(NotFound):
            {resource}Service.get_{snake}(self.tenant.id, {snake}.id)
'''


def _gen_test_properties(resource, snake, plural):
    """Generate tests/test_{snake}_properties.py content."""
    return f'''"""
Property-based tests for {resource}Service using Hypothesis.
"""
import uuid
from unittest.mock import patch

from django.test import TestCase
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from {snake}.services import {resource}Service


class {resource}PropertyTests(TestCase):
    """Property-based tests for {resource} tenant isolation and uniqueness."""

    def setUp(self):
        """Set up test tenant and user."""
        from tenants.models import Tenant
        from authentication.models import User
        from django.utils import timezone
        from datetime import timedelta

        self.tenant = Tenant.objects.create(
            id=str(uuid.uuid4()),
            subscription_tier='free',
            subscription_expiration=timezone.now() + timedelta(days=30),
        )
        self.user = User.objects.create_user(
            tenant=self.tenant,
            username='propuser',
            email='prop@example.com',
            password='testpass123',
            role='admin',
        )

    @given(st.text(min_size=1, max_size=200).filter(lambda s: s.strip()))
    @settings(max_examples=20, deadline=5000)
    def test_queries_return_only_tenant_data(self, name):
        """Property: list_{plural} returns only the authenticated tenant's data."""
        from tenants.models import Tenant
        from authentication.models import User
        from django.utils import timezone
        from datetime import timedelta

        other_tenant = Tenant.objects.create(
            id=str(uuid.uuid4()),
            subscription_tier='free',
            subscription_expiration=timezone.now() + timedelta(days=30),
        )
        other_user = User.objects.create_user(
            tenant=other_tenant,
            username=f'other_{{uuid.uuid4().hex[:8]}}',
            email=f'other_{{uuid.uuid4().hex[:8]}}@example.com',
            password='testpass123',
            role='admin',
        )
        unique_name = f'{{name}}_{{uuid.uuid4().hex[:8]}}'
        with patch('core.middleware.get_current_tenant', return_value=other_tenant.id):
            {resource}Service.create_{snake}(other_tenant.id, other_user.id, unique_name)

        results = {resource}Service.list_{plural}(self.tenant.id)
        tenant_ids = set(str(r.tenant_id) for r in results)
        self.assertNotIn(str(other_tenant.id), tenant_ids)

    @given(st.text(min_size=1, max_size=200).filter(lambda s: s.strip()))
    @settings(max_examples=20, deadline=5000)
    def test_name_uniqueness_within_tenant(self, name):
        """Property: creating two {plural} with the same name in the same tenant fails."""
        from rest_framework.exceptions import ValidationError

        unique_name = f'{{name}}_{{uuid.uuid4().hex[:8]}}'
        with patch('core.middleware.get_current_tenant', return_value=self.tenant.id):
            {resource}Service.create_{snake}(self.tenant.id, self.user.id, unique_name)
            with self.assertRaises(ValidationError):
                {resource}Service.create_{snake}(self.tenant.id, self.user.id, unique_name)

    @given(st.text(min_size=1, max_size=200).filter(lambda s: s.strip()))
    @settings(max_examples=20, deadline=5000)
    def test_cross_tenant_operations_rejected(self, name):
        """Property: accessing a {snake} from another tenant raises NotFound."""
        from tenants.models import Tenant
        from authentication.models import User
        from django.utils import timezone
        from datetime import timedelta
        from rest_framework.exceptions import NotFound

        other_tenant = Tenant.objects.create(
            id=str(uuid.uuid4()),
            subscription_tier='free',
            subscription_expiration=timezone.now() + timedelta(days=30),
        )
        other_user = User.objects.create_user(
            tenant=other_tenant,
            username=f'cross_{{uuid.uuid4().hex[:8]}}',
            email=f'cross_{{uuid.uuid4().hex[:8]}}@example.com',
            password='testpass123',
            role='admin',
        )
        unique_name = f'{{name}}_{{uuid.uuid4().hex[:8]}}'
        with patch('core.middleware.get_current_tenant', return_value=other_tenant.id):
            {snake} = {resource}Service.create_{snake}(other_tenant.id, other_user.id, unique_name)

        with self.assertRaises(NotFound):
            {resource}Service.get_{snake}(self.tenant.id, {snake}.id)
'''


def _gen_migration(resource, snake, plural, fields):
    """Generate migrations/0001_initial.py content."""
    # Build field lines for migration
    field_lines = ""
    for fn, ft in fields:
        field_lines += f"                ('{fn}', {FIELD_TYPE_MAP[ft]}),\n"

    # Build index lines
    index_lines = (
        f"models.Index(fields=['tenant'], name='idx_{plural}_tenant'), "
        f"models.Index(fields=['tenant', 'name'], name='idx_{plural}_name'), "
        f"models.Index(fields=['tenant', '-created_at'], name='idx_{plural}_created_at')"
    )

    return f"""# Generated by scaffold_resource management command

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('tenants', '0003_remove_tenant_check_subscription_tier_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='{resource}',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255)),
{field_lines}                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(db_column='created_by', on_delete=django.db.models.deletion.CASCADE, related_name='{plural}', to=settings.AUTH_USER_MODEL)),
                ('tenant', models.ForeignKey(db_column='tenant_id', on_delete=django.db.models.deletion.CASCADE, related_name='{plural}', to='tenants.tenant')),
            ],
            options={{
                'db_table': '{plural}',
                'indexes': [{index_lines}],
                'unique_together': {{('tenant', 'name')}},
            }},
        ),
    ]
"""


# ---------------------------------------------------------------------------
# Settings updater
# ---------------------------------------------------------------------------


def _add_tag_to_settings(snake, resource):
    """
    Add a new tag entry to SPECTACULAR_SETTINGS['TAGS'] in config/settings.py.
    Returns True if updated, False if already present.
    """
    settings_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "config",
        "settings.py",
    )
    with open(settings_path, "r") as f:
        content = f.read()

    new_tag = f"{{'name': '{snake}s', 'description': '{resource} CRUD - tenant-isolated resource'}}"
    if new_tag in content:
        return False

    # Insert before the closing bracket of TAGS list
    marker = "{'name': 'system'"
    if marker in content:
        content = content.replace(marker, f"{new_tag},\n        {marker}")
        with open(settings_path, "w") as f:
            f.write(content)
        return True
    return False


# ---------------------------------------------------------------------------
# Main Command
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = "Scaffold a new tenant-isolated resource following the Widget pattern."

    def add_arguments(self, parser):
        parser.add_argument(
            "name",
            type=str,
            help="PascalCase resource name (e.g. Product)",
        )
        parser.add_argument(
            "--fields",
            type=str,
            default="",
            help="Comma-separated field:type pairs (e.g. price:decimal,active:boolean)",
        )
        parser.add_argument(
            "--no-tests",
            action="store_true",
            help="Skip generating test files",
        )

    def handle(self, *args, **options):
        resource = options["name"]
        fields_raw = options["fields"]
        no_tests = options["no_tests"]

        # --- Validate resource name ---
        if not re.match(r"^[A-Z][a-zA-Z0-9]+$", resource):
            raise CommandError(
                f"Invalid resource name '{resource}'. "
                "Must be PascalCase (e.g. Product, OrderItem), no spaces or underscores."
            )

        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", resource).lower()
        plural = snake + "s"

        # Check reserved names
        if snake in RESERVED_NAMES or resource.lower() in RESERVED_NAMES:
            raise CommandError(
                f"Resource name '{resource}' conflicts with an existing app name. "
                f"Reserved names: {', '.join(sorted(RESERVED_NAMES))}"
            )

        # Check if directory already exists
        base_dir = os.getcwd()
        resource_dir = os.path.join(base_dir, snake)
        if os.path.exists(resource_dir):
            raise CommandError(
                f"Directory '{snake}/' already exists. " "Remove it or choose a different resource name."
            )

        # --- Parse --fields ---
        fields = []
        if fields_raw:
            for pair in fields_raw.split(","):
                pair = pair.strip()
                if not pair:
                    continue
                if ":" not in pair:
                    raise CommandError(
                        f"Invalid field definition '{pair}'. " "Expected format: fieldname:type (e.g. price:decimal)"
                    )
                fname, ftype = pair.split(":", 1)
                fname = fname.strip()
                ftype = ftype.strip().lower()
                if not re.match(r"^[a-z][a-z0-9_]*$", fname):
                    raise CommandError(f"Invalid field name '{fname}'. " "Must be lowercase snake_case.")
                if ftype not in FIELD_TYPE_MAP:
                    raise CommandError(
                        f"Unknown field type '{ftype}'. " f"Supported types: {', '.join(sorted(FIELD_TYPE_MAP.keys()))}"
                    )
                fields.append((fname, ftype))

        # --- Generate files ---
        generated = []

        def write_file(path, content):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(content)
            generated.append(path)

        # __init__.py
        write_file(os.path.join(resource_dir, "__init__.py"), "")

        # apps.py
        write_file(os.path.join(resource_dir, "apps.py"), _gen_apps(resource, snake))

        # models.py
        write_file(os.path.join(resource_dir, "models.py"), _gen_models(resource, snake, plural, fields))

        # services.py
        write_file(os.path.join(resource_dir, "services.py"), _gen_services(resource, snake, plural, fields))

        # serializers.py
        write_file(os.path.join(resource_dir, "serializers.py"), _gen_serializers(resource, snake, plural, fields))

        # views.py
        write_file(os.path.join(resource_dir, "views.py"), _gen_views(resource, snake, plural, fields))

        # urls.py
        write_file(os.path.join(resource_dir, "urls.py"), _gen_urls(resource, snake, plural))

        # migrations/
        write_file(os.path.join(resource_dir, "migrations", "__init__.py"), "")
        write_file(
            os.path.join(resource_dir, "migrations", "0001_initial.py"), _gen_migration(resource, snake, plural, fields)
        )

        # tests/
        if not no_tests:
            write_file(os.path.join(resource_dir, "tests", "__init__.py"), "")
            write_file(
                os.path.join(resource_dir, "tests", f"test_{snake}_service.py"),
                _gen_test_service(resource, snake, plural, fields),
            )
            write_file(
                os.path.join(resource_dir, "tests", f"test_{snake}_properties.py"),
                _gen_test_properties(resource, snake, plural),
            )

        # --- Update settings.py SPECTACULAR_SETTINGS TAGS ---
        settings_updated = _add_tag_to_settings(snake, resource)

        # --- Print results ---
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Scaffolded resource: {resource}"))
        self.stdout.write("")
        self.stdout.write("Generated files:")
        for path in generated:
            rel = os.path.relpath(path, base_dir)
            self.stdout.write(self.style.SUCCESS(f"  ✓ {rel}"))

        if settings_updated:
            self.stdout.write(
                self.style.SUCCESS(f"  ✓ config/settings.py  (added '{snake}s' tag to SPECTACULAR_SETTINGS)")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  ⚠ config/settings.py  (tag '{snake}s' already present or could not be added — add manually)"
                )
            )

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Next steps:"))
        self.stdout.write(f"  1. Add '{snake}' to INSTALLED_APPS in config/settings.py")
        self.stdout.write("  2. Add the following to api/urls.py:")
        self.stdout.write(f"       path('{plural}/', include('{snake}.urls'))")
        self.stdout.write(f"  3. Run: python manage.py makemigrations {snake}")
        self.stdout.write("  4. Run: python manage.py migrate")
        self.stdout.write(f"  5. Customize service logic in {snake}/services.py")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("Example API usage (replace <token> and <id>):"))
        self.stdout.write(f"  # List {plural}")
        self.stdout.write(f"  curl -H 'Authorization: Bearer <token>' http://localhost:8000/api/{plural}/")
        self.stdout.write(f"  # Create {snake}")
        self.stdout.write("  curl -X POST -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' \\")
        self.stdout.write(f'       -d \'{{"name": "My {resource}"}}\' http://localhost:8000/api/{plural}/')
        self.stdout.write(f"  # Get {snake}")
        self.stdout.write(f"  curl -H 'Authorization: Bearer <token>' http://localhost:8000/api/{plural}/<id>/")
        self.stdout.write(f"  # Update {snake}")
        self.stdout.write("  curl -X PATCH -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' \\")
        self.stdout.write(f'       -d \'{{"name": "Updated {resource}"}}\' http://localhost:8000/api/{plural}/<id>/')
        self.stdout.write(f"  # Delete {snake}")
        self.stdout.write(
            f"  curl -X DELETE -H 'Authorization: Bearer <token>' http://localhost:8000/api/{plural}/<id>/"
        )
        self.stdout.write("")
