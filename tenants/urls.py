"""
URL patterns for tenant management API
"""
from django.urls import path
from . import views

urlpatterns = [
    path('register/', views.register_tenant, name='tenant-register'),
    path('delete/', views.delete_tenant, name='tenant-delete'),
    path('subscription/', views.update_subscription, name='tenant-subscription'),
    path('config/', views.get_tenant_config, name='tenant-config'),
    path('audit-logs/', views.get_audit_logs, name='tenant-audit-logs'),
]