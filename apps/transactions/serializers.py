from rest_framework import serializers

from .models import Transaction


class TransactionSerializer(serializers.ModelSerializer):
    shortcode_number = serializers.CharField(source='shortcode.shortcode_number', read_only=True)
    shortcode_uid = serializers.UUIDField(source='shortcode.uid', read_only=True)

    class Meta:
        model = Transaction
        fields = [
            'uid', 'shortcode_uid', 'shortcode_number',
            'transaction_type', 'status',
            'mpesa_receipt_number', 'checkout_request_id',
            'msisdn', 'amount', 'account_reference', 'bill_ref_number',
            'transaction_desc', 'transaction_time', 'created_at',
        ]
        read_only_fields = fields
