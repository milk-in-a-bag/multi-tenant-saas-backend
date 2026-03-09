from django.contrib import admin
from .models import User, APIKey

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['username', 'email', 'tenant', 'role', 'created_at']
    list_filter = ['role', 'is_active']
    search_fields = ['username', 'email']

@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'tenant', 'revoked', 'created_at']
    list_filter = ['revoked']
