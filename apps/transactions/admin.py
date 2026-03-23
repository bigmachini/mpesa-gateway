from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Transaction


@admin.register(Transaction)
class TransactionAdmin(ModelAdmin):
    list_display = [
        'mpesa_receipt_number', 'shortcode', 'transaction_type',
        'status', 'amount', 'msisdn', 'transaction_time',
    ]
    list_filter = ['transaction_type', 'status']
    search_fields = [
        'mpesa_receipt_number', 'checkout_request_id',
        'msisdn', 'bill_ref_number', 'account_reference',
        'shortcode__shortcode_number', 'shortcode__display_name',
    ]
    readonly_fields = [
        'uid', 'shortcode', 'transaction_type', 'status',
        'mpesa_receipt_number', 'checkout_request_id',
        'msisdn', 'amount', 'account_reference', 'bill_ref_number',
        'transaction_desc', 'raw_payload', 'transaction_time', 'created_at',
    ]
    ordering = ['-transaction_time']
    date_hierarchy = 'transaction_time'

    fieldsets = [
        (None, {
            'fields': [
                'uid', 'shortcode', 'transaction_type', 'status',
                'amount', 'msisdn', 'transaction_time', 'created_at',
            ],
        }),
        ('M-Pesa References', {
            'fields': ['mpesa_receipt_number', 'checkout_request_id', 'bill_ref_number', 'account_reference'],
        }),
        ('Raw Payload', {
            'fields': ['raw_payload'],
            'classes': ['collapse'],
        }),
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
