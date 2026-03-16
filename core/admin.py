from django.contrib import admin

from .models import AuditLog, RateLimit


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["event_type", "tenant", "user", "timestamp"]
    list_filter = ["event_type", "timestamp"]
    search_fields = ["event_type"]


@admin.register(RateLimit)
class RateLimitAdmin(admin.ModelAdmin):
    list_display = ["tenant", "request_count", "window_start"]
