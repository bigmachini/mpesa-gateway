"""
Transaction recording services called from daraja.handlers.

All writes go through here. The two public functions map 1:1 to
Safaricom callback types:

  record_c2b_transaction(shortcode, payload)  — C2B confirm callback
  record_stk_callback(shortcode, payload)     — STK Push result callback

Both are idempotent: duplicate mpesa_receipt_number / checkout_request_id
is silently ignored.
"""
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError
from django.utils import timezone

from .models import Transaction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_safaricom_timestamp(ts: str) -> datetime:
    """
    Parse a Safaricom timestamp string (YYYYMMDDHHmmss) into an aware datetime.
    Falls back to now() if parsing fails.
    """
    try:
        naive = datetime.strptime(str(ts), '%Y%m%d%H%M%S')
        return timezone.make_aware(naive)
    except (ValueError, TypeError):
        logger.warning('Could not parse Safaricom timestamp %r — using now()', ts)
        return timezone.now()


def _parse_amount(raw) -> Decimal:
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return Decimal('0')


def _dispatch_post_transaction(transaction: Transaction) -> None:
    """
    Fire downstream effects after a transaction is created/completed:
      1. Credit wallet if Shared Paybill.
      2. Dispatch webhook delivery task if webhook URL is set.

    Both are deferred via try/except ImportError so the transactions app
    remains independently functional before wallets/webhooks are built.
    """
    shortcode = transaction.shortcode

    # Wallet credit (Shared Paybill only)
    if shortcode.tier == 'shared' and transaction.status == 'completed':
        try:
            from apps.wallets.services import credit_wallet
            credit_wallet(shortcode.client, transaction)
        except ImportError:
            logger.warning(
                'wallets.services not available; wallet not credited (transaction=%s)',
                transaction.uid,
            )
        except Exception:
            logger.exception('Error crediting wallet (transaction=%s)', transaction.uid)

    # Webhook dispatch
    if shortcode.webhook_url and transaction.status == 'completed':
        try:
            from apps.webhooks.tasks import dispatch_webhook
            dispatch_webhook.delay(transaction.pk)
        except ImportError:
            logger.warning(
                'webhooks.tasks not available; webhook not dispatched (transaction=%s)',
                transaction.uid,
            )
        except Exception:
            logger.exception('Error dispatching webhook (transaction=%s)', transaction.uid)


# ---------------------------------------------------------------------------
# C2B
# ---------------------------------------------------------------------------

def record_c2b_transaction(shortcode, payload: dict) -> Transaction | None:
    """
    Record an incoming C2B confirmation from Safaricom.

    Returns the Transaction on success, or None if it was a duplicate.

    Safaricom C2B payload fields used:
      TransID, TransTime, TransAmount, MSISDN,
      BillRefNumber, TransactionType
    """
    receipt = payload.get('TransID', '').strip()
    if not receipt:
        logger.error(
            'C2B payload missing TransID for shortcode=%s — cannot record', shortcode.uid
        )
        return None

    # Idempotency: receipt already exists → silently skip
    if Transaction.objects.filter(mpesa_receipt_number=receipt).exists():
        logger.info('Duplicate C2B receipt %s — skipping', receipt)
        return None

    transaction_type = (
        'c2b_paybill' if shortcode.shortcode_type == 'paybill' else 'c2b_till'
    )

    transaction = Transaction(
        shortcode=shortcode,
        transaction_type=transaction_type,
        status='completed',
        mpesa_receipt_number=receipt,
        msisdn=payload.get('MSISDN', ''),
        amount=_parse_amount(payload.get('TransAmount', '0')),
        bill_ref_number=payload.get('BillRefNumber', ''),
        account_reference=payload.get('BillRefNumber', ''),
        transaction_desc=payload.get('TransactionType', ''),
        raw_payload=payload,
        transaction_time=_parse_safaricom_timestamp(payload.get('TransTime')),
    )

    try:
        transaction.save()
    except IntegrityError:
        # Race condition: another request saved the same receipt between our
        # exists() check and the save() — safe to ignore.
        logger.info('Duplicate C2B receipt %s (race condition) — skipping', receipt)
        return None

    logger.info(
        'C2B transaction recorded: receipt=%s shortcode=%s amount=%s',
        receipt, shortcode.shortcode_number, transaction.amount,
    )

    _dispatch_post_transaction(transaction)
    return transaction


# ---------------------------------------------------------------------------
# STK Push
# ---------------------------------------------------------------------------

def create_stk_transaction(shortcode, checkout_request_id: str, phone: str, amount, account_reference: str = '') -> Transaction:
    """
    Create a pending Transaction when an STK Push is initiated.
    Called from the STK Push view before Safaricom's callback arrives.
    """
    transaction = Transaction.objects.create(
        shortcode=shortcode,
        transaction_type='stk_push',
        status='pending',
        checkout_request_id=checkout_request_id,
        msisdn=phone,
        amount=_parse_amount(amount),
        account_reference=account_reference,
        raw_payload={},
        transaction_time=timezone.now(),
    )
    logger.info(
        'STK Push transaction created: checkout_id=%s shortcode=%s amount=%s',
        checkout_request_id, shortcode.shortcode_number, transaction.amount,
    )
    return transaction


def record_stk_callback(shortcode, payload: dict) -> Transaction | None:
    """
    Update a pending STK Push Transaction when Safaricom's callback arrives.

    Payload structure:
      Body.stkCallback.ResultCode          (0 = success)
      Body.stkCallback.CheckoutRequestID
      Body.stkCallback.CallbackMetadata.Item  (only on success)
        - Amount, MpesaReceiptNumber, TransactionDate, PhoneNumber
    """
    stk = payload.get('Body', {}).get('stkCallback', {})
    checkout_id = stk.get('CheckoutRequestID', '').strip()
    result_code = stk.get('ResultCode')

    if not checkout_id:
        logger.error('STK callback missing CheckoutRequestID for shortcode=%s', shortcode.uid)
        return None

    try:
        transaction = Transaction.objects.get(
            checkout_request_id=checkout_id,
            shortcode=shortcode,
        )
    except Transaction.DoesNotExist:
        logger.warning(
            'STK callback for unknown checkout_id=%s shortcode=%s — creating record',
            checkout_id, shortcode.uid,
        )
        # Create a record even if we missed the initiation (e.g. restart during push)
        transaction = Transaction(
            shortcode=shortcode,
            transaction_type='stk_push',
            checkout_request_id=checkout_id,
            msisdn='',
            amount=Decimal('0'),
            raw_payload=payload,
            transaction_time=timezone.now(),
        )

    if result_code == 0:
        # Extract metadata items
        items = {
            item['Name']: item.get('Value')
            for item in stk.get('CallbackMetadata', {}).get('Item', [])
        }
        receipt = str(items.get('MpesaReceiptNumber', '')).strip()

        # Idempotency: transaction already completed with this receipt
        if transaction.pk and transaction.status == 'completed':
            logger.info('STK receipt %s already recorded — skipping duplicate callback', receipt)
            return None

        # Idempotency: receipt recorded against a different transaction (shouldn't happen)
        if receipt and Transaction.objects.filter(mpesa_receipt_number=receipt).exclude(pk=transaction.pk).exists():
            logger.info('Duplicate STK receipt %s on different transaction — skipping', receipt)
            return None

        transaction.status = 'completed'
        transaction.mpesa_receipt_number = receipt or None
        transaction.amount = _parse_amount(items.get('Amount', transaction.amount))
        transaction.msisdn = str(items.get('PhoneNumber', transaction.msisdn))
        transaction.transaction_time = _parse_safaricom_timestamp(items.get('TransactionDate'))
        transaction.raw_payload = payload

        logger.info(
            'STK Push completed: receipt=%s checkout_id=%s amount=%s',
            receipt, checkout_id, transaction.amount,
        )
    else:
        transaction.status = 'failed'
        transaction.raw_payload = payload
        logger.info(
            'STK Push failed: checkout_id=%s ResultCode=%s', checkout_id, result_code
        )

    try:
        transaction.save()
    except IntegrityError:
        logger.info('Duplicate STK receipt (race condition) — skipping', )
        return None

    _dispatch_post_transaction(transaction)
    return transaction
