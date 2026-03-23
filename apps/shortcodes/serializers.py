from django.conf import settings
from rest_framework import serializers

from .models import PaymentReference, Shortcode, generate_account_code, suggest_account_codes


class ShortcodeSerializer(serializers.ModelSerializer):
    callback_urls = serializers.SerializerMethodField(read_only=True)
    # account_code is writable on create for Shared Till (client preference),
    # but read-only on updates — code cannot be changed after assignment.
    account_code = serializers.CharField(max_length=6, required=False, allow_blank=True)

    class Meta:
        model = Shortcode
        fields = [
            'uid', 'shortcode_type', 'tier', 'shortcode_number', 'display_name',
            'account_code', 'consumer_key', 'consumer_secret', 'passkey', 'initiator_name',
            'webhook_url',
            'enable_c2b_validation', 'validation_mode', 'validation_webhook_url',
            'is_active', 'created_at', 'callback_urls',
        ]
        read_only_fields = ['uid', 'created_at', 'callback_urls']
        extra_kwargs = {
            'consumer_key': {'write_only': True},
            'consumer_secret': {'write_only': True},
            'passkey': {'write_only': True},
            'shortcode_number': {'required': False},
            'display_name': {'required': False},  # auto-set from business_name for Shared Paybill
            'validation_mode': {'required': False},
            'validation_webhook_url': {'required': False},
        }

    def get_callback_urls(self, obj):
        return obj.get_callback_urls()

    def validate_account_code(self, value):
        if not value:
            return value
        if not value.isdigit() or len(value) != 6:
            raise serializers.ValidationError("Account code must be exactly 6 digits.")
        return value

    def validate(self, attrs):
        tier = attrs.get('tier', getattr(self.instance, 'tier', None))
        shortcode_type = attrs.get('shortcode_type', getattr(self.instance, 'shortcode_type', None))

        # Shared Till is Paybill only — Lipa na M-Pesa has no account number field
        if tier == 'shared' and shortcode_type == 'till':
            raise serializers.ValidationError(
                {'tier': "Shared Paybill is only available for Paybill shortcodes, not Lipa na M-Pesa (Buy Goods)."}
            )

        if tier == 'shared':
            attrs['shortcode_number'] = settings.DARAJA_SHORTCODE

            # Auto-set display_name from platform config
            if not self.instance:
                attrs['display_name'] = settings.DARAJA_DISPLAY_NAME

            # Handle preferred account_code
            preferred = attrs.get('account_code', '').strip()
            if preferred:
                if Shortcode.objects.filter(account_code=preferred).exists():
                    suggestions = suggest_account_codes(preferred)
                    raise serializers.ValidationError({
                        'account_code': (
                            f"Account code {preferred} is already taken. "
                            f"Available suggestions: {', '.join(suggestions)}."
                        )
                    })
                # Preferred code is available — keep it in attrs
            else:
                # No preference — will be auto-generated in create()
                attrs.pop('account_code', None)

        else:
            if not attrs.get('shortcode_number') and not getattr(self.instance, 'shortcode_number', None):
                raise serializers.ValidationError({'shortcode_number': "This field is required."})
            if not attrs.get('display_name') and not getattr(self.instance, 'display_name', None):
                raise serializers.ValidationError({'display_name': "This field is required."})

        if tier == 'byoc':
            required = ['consumer_key', 'consumer_secret']
            if shortcode_type == 'paybill':
                required.append('passkey')
            for field in required:
                if not attrs.get(field) and not getattr(self.instance, field, None):
                    raise serializers.ValidationError(
                        {field: "Required for BYOC shortcodes."}
                    )

        # Validate C2B validation config
        enable_validation = attrs.get(
            'enable_c2b_validation',
            getattr(self.instance, 'enable_c2b_validation', False),
        )
        if enable_validation:
            mode = attrs.get('validation_mode', getattr(self.instance, 'validation_mode', ''))
            if not mode:
                raise serializers.ValidationError(
                    {'validation_mode': "Select a validation mode when C2B validation is enabled."}
                )
            if mode == 'webhook':
                webhook_url = attrs.get(
                    'validation_webhook_url',
                    getattr(self.instance, 'validation_webhook_url', None),
                )
                if not webhook_url:
                    raise serializers.ValidationError(
                        {'validation_webhook_url': "A webhook URL is required for webhook validation mode."}
                    )

        # Prevent account_code changes after creation
        if self.instance and 'account_code' in attrs:
            attrs.pop('account_code')

        # Validate unique_together (client + shortcode_number) because client is
        # injected in perform_create and not visible to the serializer.
        request = self.context.get('request')
        if request and not self.instance:
            shortcode_number = attrs.get('shortcode_number')
            if Shortcode.objects.filter(client=request.user.company, shortcode_number=shortcode_number).exists():
                raise serializers.ValidationError(
                    {'shortcode_number': 'You already have a shortcode with this number.'}
                )

        return attrs

    def create(self, validated_data):
        if validated_data.get('tier') == 'shared' and not validated_data.get('account_code'):
            validated_data['account_code'] = generate_account_code()
        return super().create(validated_data)


class WebhookURLSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shortcode
        fields = ['webhook_url']


class PaymentReferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentReference
        fields = ['id', 'reference', 'amount', 'expires_at', 'is_used', 'created_at']
        read_only_fields = ['id', 'is_used', 'created_at']

    def validate_expires_at(self, value):
        from django.utils import timezone
        if value <= timezone.now():
            raise serializers.ValidationError("expires_at must be in the future.")
        return value

    def validate(self, attrs):
        # Uniqueness check: (shortcode, reference) — shortcode is injected in perform_create
        shortcode = self.context.get('shortcode')
        if shortcode and PaymentReference.objects.filter(
            shortcode=shortcode, reference=attrs.get('reference', '')
        ).exists():
            raise serializers.ValidationError(
                {'reference': 'A payment reference with this value already exists for this shortcode.'}
            )
        return attrs
