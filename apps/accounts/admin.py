from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from unfold.admin import ModelAdmin

from .models import Client


@admin.register(Client)
class ClientAdmin(ModelAdmin, BaseUserAdmin):
    list_display = ['email', 'business_name', 'tier', 'is_active', 'created_at']
    list_filter = ['tier', 'is_active']
    search_fields = ['email', 'business_name', 'phone_number']
    ordering = ['-created_at']

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Business Info', {'fields': ('business_name', 'phone_number', 'tier')}),
    )

    actions = ['activate_clients', 'deactivate_clients']

    @admin.action(description='Activate selected clients')
    def activate_clients(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description='Deactivate selected clients')
    def deactivate_clients(self, request, queryset):
        queryset.update(is_active=False)
