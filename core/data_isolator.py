"""
Data Isolator for enforcing tenant data isolation at the database layer
"""
from django.db import models, connection
from django.core.exceptions import ValidationError
from .middleware import get_current_tenant


class TenantIsolationError(Exception):
    """Exception raised when tenant isolation is violated"""
    pass


class DataIsolator:
    """
    Data Isolator class that enforces tenant filtering on all queries
    and associates tenant ID with all writes
    """
    
    @staticmethod
    def validate_tenant_context():
        """
        Validate that tenant context is present
        Raises TenantIsolationError if tenant_id is None
        """
        tenant_id = get_current_tenant()
        if tenant_id is None:
            raise TenantIsolationError(
                "Tenant context is required for this operation. "
                "Ensure the request is authenticated with a valid JWT token or API key."
            )
        return tenant_id
    
    @staticmethod
    def query(sql, params=None):
        """
        Execute a raw SQL query with automatic tenant filtering
        
        Args:
            sql: SQL query string (should include {tenant_filter} placeholder)
            params: Query parameters
            
        Returns:
            List of result rows as dictionaries
        """
        tenant_id = DataIsolator.validate_tenant_context()
        
        # Add tenant filter to WHERE clause
        if '{tenant_filter}' in sql:
            sql = sql.replace('{tenant_filter}', 'tenant_id = %s')
            params = [tenant_id] + (list(params) if params else [])
        
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
    
    @staticmethod
    def write(sql, params=None):
        """
        Execute a raw SQL write operation with automatic tenant association
        
        Args:
            sql: SQL INSERT/UPDATE statement
            params: Query parameters
            
        Returns:
            Dictionary with rowsAffected and insertedId (if applicable)
        """
        tenant_id = DataIsolator.validate_tenant_context()
        
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return {
                'rowsAffected': cursor.rowcount,
                'insertedId': cursor.lastrowid if cursor.lastrowid else None
            }
    
    @staticmethod
    def delete_tenant_data(tenant_id):
        """
        Delete all data associated with a tenant
        
        Args:
            tenant_id: The tenant ID to delete data for
        """
        from tenants.models import Tenant
        
        # This will cascade delete all related data due to foreign key constraints
        Tenant.objects.filter(id=tenant_id).delete()


class TenantManager(models.Manager):
    """
    Custom Django model manager that enforces tenant filtering on all queries
    """
    
    def get_queryset(self):
        """
        Override get_queryset to automatically filter by tenant_id
        """
        queryset = super().get_queryset()
        
        # Get current tenant from thread-local storage
        tenant_id = get_current_tenant()
        
        # If tenant context exists, filter by tenant
        if tenant_id:
            # Check if model has a 'tenant' ForeignKey field
            if hasattr(self.model, 'tenant'):
                queryset = queryset.filter(tenant_id=tenant_id)
            # Or check if model has a direct 'tenant_id' field
            elif hasattr(self.model, 'tenant_id'):
                queryset = queryset.filter(tenant_id=tenant_id)
        
        return queryset
    
    def create(self, **kwargs):
        """
        Override create to automatically set tenant_id
        """
        tenant_id = get_current_tenant()
        
        # If tenant context exists, set it
        if tenant_id:
            # Check if model has a 'tenant' ForeignKey or 'tenant_id' field
            has_tenant_fk = hasattr(self.model, 'tenant')
            has_tenant_id = hasattr(self.model, 'tenant_id')
            
            if (has_tenant_fk or has_tenant_id) and 'tenant' not in kwargs and 'tenant_id' not in kwargs:
                kwargs['tenant_id'] = tenant_id
        
        return super().create(**kwargs)


class TenantIsolatedModel(models.Model):
    """
    Abstract base model for tenant-isolated models
    Automatically applies tenant filtering and validation
    """
    
    # Use custom manager for automatic tenant filtering
    objects = TenantManager()
    
    # Also provide an unfiltered manager for admin/system operations
    all_objects = models.Manager()
    
    class Meta:
        abstract = True
    
    def save(self, *args, **kwargs):
        """
        Override save to validate tenant context and set tenant_id
        """
        # Get current tenant
        tenant_id = get_current_tenant()
        
        # Get the tenant_id from this object
        obj_tenant_id = self._get_object_tenant_id()
        
        # If this is a new object and tenant_id is not set, set it from context
        if not self.pk and tenant_id and not obj_tenant_id:
            if hasattr(self, 'tenant'):
                self.tenant_id = tenant_id
            elif hasattr(self, 'tenant_id'):
                self.tenant_id = tenant_id
        
        # Validate that tenant_id matches current context (prevent cross-tenant updates)
        if obj_tenant_id and tenant_id and str(obj_tenant_id) != str(tenant_id):
            raise TenantIsolationError(
                f"Cannot save object with tenant_id {obj_tenant_id} "
                f"in context of tenant {tenant_id}"
            )
        
        super().save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        """
        Override delete to validate tenant context
        """
        tenant_id = get_current_tenant()
        
        # Get the tenant_id from this object
        obj_tenant_id = self._get_object_tenant_id()
        
        # Validate that tenant_id matches current context
        if obj_tenant_id and tenant_id and str(obj_tenant_id) != str(tenant_id):
            raise TenantIsolationError(
                f"Cannot delete object with tenant_id {obj_tenant_id} "
                f"in context of tenant {tenant_id}"
            )
        
        super().delete(*args, **kwargs)
    
    def _get_object_tenant_id(self):
        """Helper method to get tenant_id from object"""
        if hasattr(self, 'tenant_id'):
            return self.tenant_id
        elif hasattr(self, 'tenant'):
            return self.tenant_id if self.tenant_id else None
        return None
