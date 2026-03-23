import random
import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from encrypted_model_fields.fields import EncryptedCharField


def generate_account_code():
    """Auto-generate a unique 6-digit account code."""
    while True:
        code = f"{random.randint(100000, 999999):06d}"
        if not Shortcode.objects.filter(account_code=code).exists():
            return code


def suggest_account_codes(preferred: str, count: int = 5) -> list[str]:
    """
    Return up to `count` available codes numerically close to `preferred`.
    Walks outward from the preferred number (±1, ±2, ...) and collects
    available codes until we have enough or exhaust the range.
    """
    base = int(preferred)
    taken = set(Shortcode.objects.filter(account_code__isnull=False).values_list('account_code', flat=True))
    suggestions = []
    step = 1
    while len(suggestions) < count and step <= 999999:
        for candidate in (base + step, base - step):
            if 0 <= candidate <= 999999:
                code = f"{candidate:06d}"
                if code != preferred and code not in taken:
                    suggestions.append(code)
                    if len(suggestions) == count:
                        break
        step += 1
    return suggestions


class Shortcode(models.Model):
    SHORTCODE_TYPES = [
        ('paybill', 'Paybill'),
        ('till', 'Lipa na M-Pesa (Buy Goods)'),
    ]
    TIER_TYPES = [
        ('byoc', 'Bring Your Own Credentials'),
        ('shared', 'Shared Paybill'),
    ]
    VALIDATION_MODES = [
        ('pre_register', 'Pre-registered References'),
        ('webhook', 'Webhook (real-time)'),
    ]

    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='shortcodes',
    )
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    shortcode_type = models.CharField(max_length=20, choices=SHORTCODE_TYPES)
    tier = models.CharField(max_length=20, choices=TIER_TYPES)
    shortcode_number = models.CharField(max_length=20)
    display_name = models.CharField(max_length=255)

    # Shared Till only — 6-digit code the client's customers enter before # when paying.
    # Null for BYOC shortcodes. Unique across the platform since all Shared Till
    # payments land on the same Paybill; this code is how we route them.
    account_code = models.CharField(max_length=6, unique=True, blank=True, null=True)

    # Daraja credentials — encrypted at rest, BYOC only
    consumer_key = EncryptedCharField(max_length=255, blank=True)
    consumer_secret = EncryptedCharField(max_length=255, blank=True)
    passkey = EncryptedCharField(max_length=500, blank=True)
    initiator_name = EncryptedCharField(max_length=255, blank=True)

    webhook_url = models.URLField(blank=True, null=True)

    # C2B payment validation (Paybill only)
    enable_c2b_validation = models.BooleanField(default=False)
    validation_mode = models.CharField(
        max_length=20, choices=VALIDATION_MODES, blank=True, default='',
    )
    validation_webhook_url = models.URLField(blank=True, null=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('client', 'shortcode_number')
        ordering = ['-created_at']

    def clean(self):
        if self.shortcode_type == 'till' and self.tier == 'shared':
            raise ValidationError(
                {'tier': "Shared Paybill is only available for Paybill shortcodes, not Lipa na M-Pesa (Buy Goods)."}
            )
        if self.enable_c2b_validation:
            if not self.validation_mode:
                raise ValidationError(
                    {'validation_mode': "Select a validation mode when C2B validation is enabled."}
                )
            if self.validation_mode == 'webhook' and not self.validation_webhook_url:
                raise ValidationError(
                    {'validation_webhook_url': "A webhook URL is required for webhook validation mode."}
                )

    def __str__(self):
        return f"{self.display_name} ({self.shortcode_number})"

    def get_callback_urls(self):
        base = settings.PLATFORM_BASE_URL
        return {
            'c2b_confirmation': f"{base}/api/v1/callback/c2b/{self.uid}/confirm/",
            'c2b_validation': f"{base}/api/v1/callback/c2b/{self.uid}/validate/",
            'stk_callback': f"{base}/api/v1/callback/stk/{self.uid}/callback/",
        }


class PaybillShortcode(Shortcode):
    """Proxy model for Paybill shortcodes (BYOC or Shared Paybill tier)."""
    class Meta:
        proxy = True
        verbose_name = 'Paybill Shortcode'
        verbose_name_plural = 'Paybill Shortcodes'


class TillShortcode(Shortcode):
    """Proxy model for Lipa na M-Pesa (Buy Goods) shortcodes — always BYOC."""
    class Meta:
        proxy = True
        verbose_name = 'Lipa na M-Pesa Shortcode'
        verbose_name_plural = 'Lipa na M-Pesa Shortcodes'


class PaymentReference(models.Model):
    """
    A pre-registered payment reference for C2B validation (pre_register mode).

    The client registers an expected payment (reference + amount) before directing
    their customer to pay. When Safaricom calls c2b_validate, we look up the reference
    and only accept if the amount matches and the reference has not expired or been used.
    """
    shortcode = models.ForeignKey(
        Shortcode, on_delete=models.CASCADE, related_name='payment_references',
    )
    reference = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('shortcode', 'reference')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.reference} — {self.amount} ({self.shortcode})"

    def is_valid_for(self, amount: Decimal) -> bool:
        """Return True if this reference is still usable and amount matches exactly."""
        return (
            not self.is_used
            and self.expires_at > timezone.now()
            and self.amount == amount
        )
