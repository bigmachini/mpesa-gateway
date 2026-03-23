from django import forms
from django.conf import settings
from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    PaybillShortcode, PaymentReference, Shortcode, TillShortcode,
    generate_account_code, suggest_account_codes,
)
from .widgets import AccountCodeWidget


# ---------------------------------------------------------------------------
# PaymentReference inline (shown inside Paybill shortcode change view)
# ---------------------------------------------------------------------------

class PaymentReferenceInline(TabularInline):
    model = PaymentReference
    extra = 0
    fields = ['reference', 'amount', 'expires_at', 'is_used', 'created_at']
    readonly_fields = ['reference', 'amount', 'expires_at', 'is_used', 'created_at']
    ordering = ['-created_at']
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


# ---------------------------------------------------------------------------
# Paybill admin
# ---------------------------------------------------------------------------

class PaybillShortcodeForm(forms.ModelForm):
    account_code = forms.CharField(max_length=6, required=False)

    class Meta:
        model = PaybillShortcode
        fields = [
            'client', 'tier', 'display_name', 'shortcode_number',
            'consumer_key', 'consumer_secret', 'passkey', 'initiator_name',
            'account_code', 'webhook_url', 'is_active',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only Paybill tiers allowed here
        self.fields['tier'].choices = Shortcode.TIER_TYPES

        if 'account_code' in self.fields:
            is_existing = bool(self.instance and self.instance.pk and self.instance.account_code)
            self.fields['account_code'].widget = AccountCodeWidget(is_existing=is_existing)

    def clean(self):
        cleaned_data = super().clean()
        tier = cleaned_data.get('tier')

        if tier == 'shared':
            # System-managed — override whatever was submitted
            cleaned_data['shortcode_number'] = settings.DARAJA_SHORTCODE
            cleaned_data['display_name'] = settings.DARAJA_DISPLAY_NAME

            preferred = (cleaned_data.get('account_code') or '').strip()
            if preferred:
                if len(preferred) != 6 or not preferred.isdigit():
                    self.add_error('account_code', "Account code must be exactly 6 digits.")
                elif (
                    Shortcode.objects.filter(account_code=preferred)
                    .exclude(pk=self.instance.pk if self.instance else None)
                    .exists()
                ):
                    suggestions = suggest_account_codes(preferred)
                    self.add_error(
                        'account_code',
                        f"Account code {preferred} is already taken. "
                        f"Available suggestions: {', '.join(suggestions)}.",
                    )
            else:
                cleaned_data['account_code'] = None  # auto-generated on save

        elif tier == 'byoc':
            if not cleaned_data.get('shortcode_number'):
                self.add_error('shortcode_number', "Required for BYOC shortcodes.")
            if not cleaned_data.get('display_name'):
                self.add_error('display_name', "Required for BYOC shortcodes.")
            for cred in ('consumer_key', 'consumer_secret', 'passkey'):
                if not cleaned_data.get(cred):
                    self.add_error(cred, "Required for BYOC shortcodes.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.shortcode_type = 'paybill'
        if instance.tier == 'shared' and not instance.account_code:
            instance.account_code = generate_account_code()
        if commit:
            instance.save()
        return instance


@admin.register(PaybillShortcode)
class PaybillShortcodeAdmin(ModelAdmin):
    form = PaybillShortcodeForm
    inlines = [PaymentReferenceInline]
    list_display = ['display_name', 'shortcode_number', 'tier', 'account_code', 'client', 'is_active', 'created_at']
    list_filter = ['tier', 'is_active']
    search_fields = ['display_name', 'shortcode_number', 'client__email', 'client__business_name']
    readonly_fields = ['uid', 'created_at']
    ordering = ['-created_at']
    actions = ['activate_shortcodes', 'deactivate_shortcodes']

    _VALIDATION_FIELDSET = ('C2B Payment Validation', {
        'description': (
            'Enable to have Safaricom call our validation endpoint before confirming payments. '
            'Pre-register mode: client registers references via API. '
            'Webhook mode: we call the client\'s URL in real time.'
        ),
        'fields': ['enable_c2b_validation', 'validation_mode', 'validation_webhook_url'],
    })

    # Fieldsets for adding (tier not yet known — show everything)
    _ADD_FIELDSETS = [
        (None, {'fields': ['client', 'tier', 'is_active', 'webhook_url']}),
        ('BYOC — Bring Your Own Credentials', {
            'description': 'Fill this section when Tier = BYOC.',
            'fields': ['display_name', 'shortcode_number',
                       'consumer_key', 'consumer_secret', 'passkey', 'initiator_name'],
        }),
        ('Shared Paybill', {
            'description': 'Fill this section when Tier = Shared Paybill. '
                           'Display name and shortcode number are set from platform config.',
            'fields': ['account_code'],
        }),
        _VALIDATION_FIELDSET,
    ]

    # Fieldsets when editing a BYOC paybill
    _BYOC_FIELDSETS = [
        (None, {'fields': ['client', 'tier', 'display_name', 'shortcode_number',
                            'is_active', 'webhook_url', 'uid', 'created_at']}),
        ('Daraja Credentials', {
            'fields': ['consumer_key', 'consumer_secret', 'passkey', 'initiator_name'],
        }),
        _VALIDATION_FIELDSET,
    ]

    # Fieldsets when editing a Shared Paybill
    _SHARED_FIELDSETS = [
        (None, {'fields': ['client', 'tier', 'display_name', 'shortcode_number',
                            'account_code', 'is_active', 'webhook_url', 'uid', 'created_at']}),
        _VALIDATION_FIELDSET,
    ]

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return self._ADD_FIELDSETS
        if obj.tier == 'shared':
            return self._SHARED_FIELDSETS
        return self._BYOC_FIELDSETS

    def get_readonly_fields(self, request, obj=None):
        base = ['uid', 'created_at']
        if obj and obj.tier == 'shared':
            # System-managed — show but lock
            base += ['display_name', 'shortcode_number', 'account_code']
        return base

    def get_queryset(self, request):
        return super().get_queryset(request).filter(shortcode_type='paybill')

    @admin.action(description='Activate selected shortcodes')
    def activate_shortcodes(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description='Deactivate selected shortcodes')
    def deactivate_shortcodes(self, request, queryset):
        queryset.update(is_active=False)


# ---------------------------------------------------------------------------
# Lipa na M-Pesa (Till) admin
# ---------------------------------------------------------------------------

class TillShortcodeForm(forms.ModelForm):
    class Meta:
        model = TillShortcode
        fields = [
            'client', 'display_name', 'shortcode_number',
            'consumer_key', 'consumer_secret',
            'webhook_url', 'is_active',
        ]

    def clean(self):
        cleaned_data = super().clean()
        for field in ('display_name', 'shortcode_number', 'consumer_key', 'consumer_secret'):
            if not cleaned_data.get(field):
                self.add_error(field, "This field is required.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.shortcode_type = 'till'
        instance.tier = 'byoc'
        if commit:
            instance.save()
        return instance


@admin.register(TillShortcode)
class TillShortcodeAdmin(ModelAdmin):
    form = TillShortcodeForm
    list_display = ['display_name', 'shortcode_number', 'client', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['display_name', 'shortcode_number', 'client__email', 'client__business_name']
    readonly_fields = ['uid', 'created_at']
    ordering = ['-created_at']
    actions = ['activate_shortcodes', 'deactivate_shortcodes']

    fieldsets = [
        (None, {'fields': ['client', 'display_name', 'shortcode_number',
                            'is_active', 'webhook_url', 'uid', 'created_at']}),
        ('Daraja Credentials', {
            'fields': ['consumer_key', 'consumer_secret'],
        }),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).filter(shortcode_type='till')

    @admin.action(description='Activate selected shortcodes')
    def activate_shortcodes(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description='Deactivate selected shortcodes')
    def deactivate_shortcodes(self, request, queryset):
        queryset.update(is_active=False)


# ---------------------------------------------------------------------------
# PaymentReference standalone admin
# ---------------------------------------------------------------------------

@admin.register(PaymentReference)
class PaymentReferenceAdmin(ModelAdmin):
    list_display = ['reference', 'shortcode', 'amount', 'expires_at', 'is_used', 'created_at']
    list_filter = ['is_used']
    search_fields = ['reference', 'shortcode__display_name', 'shortcode__shortcode_number']
    readonly_fields = ['shortcode', 'reference', 'amount', 'expires_at', 'is_used', 'created_at']
    ordering = ['-created_at']
    date_hierarchy = 'created_at'

    fieldsets = [
        (None, {'fields': ['shortcode', 'reference', 'amount', 'expires_at']}),
        ('Status', {'fields': ['is_used', 'created_at']}),
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
