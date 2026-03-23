from rest_framework import serializers


class STKPushSerializer(serializers.Serializer):
    shortcode_uid = serializers.UUIDField()
    phone = serializers.CharField(max_length=20)
    amount = serializers.IntegerField(min_value=1)
    # Safaricom limits AccountReference to 12 chars, TransactionDesc to 13
    account_reference = serializers.CharField(max_length=12)
    description = serializers.CharField(max_length=13)

    def validate_phone(self, value):
        # Normalise: strip spaces, ensure starts with 254
        phone = value.strip().replace(' ', '')
        if phone.startswith('0'):
            phone = '254' + phone[1:]
        elif phone.startswith('+'):
            phone = phone[1:]
        if not phone.startswith('254') or not phone.isdigit() or len(phone) != 12:
            raise serializers.ValidationError(
                'Phone must be a valid Kenyan number in format 2547XXXXXXXX.'
            )
        return phone


class STKPushResponseSerializer(serializers.Serializer):
    """Read-only serializer that documents the Daraja STK Push response shape."""
    MerchantRequestID = serializers.CharField(read_only=True)
    CheckoutRequestID = serializers.CharField(read_only=True)
    ResponseCode = serializers.CharField(read_only=True)
    ResponseDescription = serializers.CharField(read_only=True)
    CustomerMessage = serializers.CharField(read_only=True)
