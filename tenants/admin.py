from django.contrib import admin

from .models import Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["id", "subscription_tier", "status", "created_at"]
    list_filter = ["subscription_tier", "status"]
    search_fields = ["id"]
