import uuid

from django.db import models


class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('c2b_paybill', 'C2B Paybill'),
        ('c2b_till', 'C2B Lipa na M-Pesa'),
        ('stk_push', 'STK Push'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),       # STK Push initiated, awaiting callback
        ('completed', 'Completed'),   # Successfully received
        ('failed', 'Failed'),         # STK Push failed or cancelled
    ]

    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    shortcode = models.ForeignKey(
        'shortcodes.Shortcode',
        on_delete=models.PROTECT,
        related_name='transactions',
    )
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # M-Pesa identifiers
    mpesa_receipt_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
    checkout_request_id = models.CharField(max_length=100, null=True, blank=True)  # STK Push only

    # Payer / payment details
    msisdn = models.CharField(max_length=20)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    account_reference = models.CharField(max_length=100, blank=True)
    bill_ref_number = models.CharField(max_length=100, blank=True)
    transaction_desc = models.TextField(blank=True)

    # Exact JSON from Safaricom — never modified
    raw_payload = models.JSONField()

    transaction_time = models.DateTimeField()  # Safaricom's timestamp
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-transaction_time']
        indexes = [
            models.Index(fields=['shortcode', 'status']),
            models.Index(fields=['mpesa_receipt_number']),
            models.Index(fields=['msisdn']),
            models.Index(fields=['checkout_request_id']),
        ]

    def __str__(self):
        return f"{self.mpesa_receipt_number or self.checkout_request_id} — {self.amount} ({self.status})"
