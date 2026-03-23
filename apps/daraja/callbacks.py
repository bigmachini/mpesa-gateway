"""
Unauthenticated views that receive Safaricom postbacks.

Safaricom does not send auth headers — these endpoints are public but
restricted to Safaricom IP ranges in production via @safaricom_ip_required.
They must always return HTTP 200 with {"ResultCode": 0, "ResultDesc": "Accepted"}.
"""
import json
import logging
from decimal import Decimal, InvalidOperation

import httpx
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.shortcodes.models import PaymentReference, Shortcode
from .handlers import handle_c2b_confirmation, handle_stk_callback
from .utils import safaricom_ip_required

logger = logging.getLogger(__name__)

ACCEPTED = {'ResultCode': 0, 'ResultDesc': 'Accepted'}
REJECTED = {'ResultCode': 1, 'ResultDesc': 'Rejected'}


def _get_shortcode(uid):
    try:
        return Shortcode.objects.get(uid=uid, is_active=True)
    except Shortcode.DoesNotExist:
        return None


def _extract_reference(shortcode, bill_ref: str) -> str:
    """
    Extract the payment reference from BillRefNumber.

    Shared Paybill format: "<account_code>#<reference>"
    BYOC format: "<reference>" (the full BillRefNumber is the reference)
    """
    if shortcode.tier == 'shared' and '#' in bill_ref:
        return bill_ref.split('#', 1)[1].strip()
    return bill_ref.strip()


@csrf_exempt
@require_POST
@safaricom_ip_required
def c2b_validate(request, uid):
    """
    C2B Validation — Safaricom asks whether to accept a payment.

    If the shortcode has C2B validation disabled we accept immediately.
    Otherwise we branch on validation_mode:

    - pre_register: look up the PaymentReference, check amount, mark used.
    - webhook: forward the payload to the client's validation URL and mirror
      their ResultCode. Timeout or unreachable → reject (ResponseType=Cancelled
      was registered, so Safaricom expects a decisive answer here).
    """
    shortcode = _get_shortcode(uid)
    if not shortcode:
        logger.warning('C2B validate received for unknown/inactive shortcode uid=%s', uid)
        return JsonResponse(ACCEPTED)

    if not shortcode.enable_c2b_validation:
        return JsonResponse(ACCEPTED)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error('C2B validate received malformed JSON for shortcode uid=%s', uid)
        return JsonResponse(REJECTED)

    bill_ref = payload.get('BillRefNumber', '')
    try:
        amount = Decimal(str(payload.get('TransAmount', '0')))
    except InvalidOperation:
        logger.error('C2B validate received invalid amount for shortcode uid=%s', uid)
        return JsonResponse(REJECTED)

    logger.info(
        'C2B validate: shortcode=%s BillRefNumber=%s Amount=%s mode=%s',
        shortcode.shortcode_number, bill_ref, amount, shortcode.validation_mode,
    )

    if shortcode.validation_mode == 'pre_register':
        reference = _extract_reference(shortcode, bill_ref)
        try:
            ref_obj = PaymentReference.objects.get(
                shortcode=shortcode, reference=reference,
            )
        except PaymentReference.DoesNotExist:
            logger.warning(
                'C2B validate: unknown reference=%s for shortcode=%s',
                reference, shortcode.shortcode_number,
            )
            return JsonResponse(REJECTED)

        if not ref_obj.is_valid_for(amount):
            logger.warning(
                'C2B validate: reference=%s invalid (used=%s, amount_expected=%s, amount_received=%s)',
                reference, ref_obj.is_used, ref_obj.amount, amount,
            )
            return JsonResponse(REJECTED)

        # Mark as used atomically before returning
        PaymentReference.objects.filter(pk=ref_obj.pk, is_used=False).update(is_used=True)
        logger.info('C2B validate: accepted reference=%s shortcode=%s', reference, shortcode.shortcode_number)
        return JsonResponse(ACCEPTED)

    if shortcode.validation_mode == 'webhook':
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.post(
                    shortcode.validation_webhook_url,
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                )
            result = resp.json()
            result_code = result.get('ResultCode', 1)
            if result_code == 0:
                logger.info(
                    'C2B validate: webhook accepted payment for shortcode=%s', shortcode.shortcode_number
                )
                return JsonResponse(ACCEPTED)
            logger.info(
                'C2B validate: webhook rejected payment for shortcode=%s ResultCode=%s',
                shortcode.shortcode_number, result_code,
            )
            return JsonResponse(REJECTED)
        except Exception:
            logger.exception(
                'C2B validate: webhook call failed for shortcode=%s — rejecting', shortcode.shortcode_number
            )
            return JsonResponse(REJECTED)

    # Unknown mode — fail safe: reject
    logger.error('C2B validate: unknown validation_mode=%s for shortcode=%s', shortcode.validation_mode, uid)
    return JsonResponse(REJECTED)


@csrf_exempt
@require_POST
@safaricom_ip_required
def c2b_confirm(request, uid):
    """
    C2B Confirmation — payment has been received by Safaricom.
    Parse payload, record transaction, credit wallet (Shared Paybill),
    dispatch webhook. Always return ACCEPTED.

    Payload fields (Safaricom C2B):
        TransactionType, TransID, TransTime, TransAmount,
        BusinessShortCode, BillRefNumber, InvoiceNumber,
        OrgAccountBalance, ThirdPartyTransID,
        MSISDN, FirstName, MiddleName, LastName
    """
    shortcode = _get_shortcode(uid)
    if not shortcode:
        logger.warning('C2B confirm for unknown/inactive shortcode uid=%s', uid)
        return JsonResponse(ACCEPTED)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error('C2B confirm received malformed JSON for shortcode uid=%s', uid)
        return JsonResponse(ACCEPTED)

    logger.info(
        'C2B confirm received: shortcode=%s TransID=%s Amount=%s MSISDN=%s',
        shortcode.shortcode_number,
        payload.get('TransID'),
        payload.get('TransAmount'),
        payload.get('MSISDN'),
    )

    try:
        handle_c2b_confirmation(shortcode, payload)
    except Exception:
        logger.exception('Unhandled error in C2B confirmation handler (shortcode=%s)', uid)
    return JsonResponse(ACCEPTED)


@csrf_exempt
@require_POST
@safaricom_ip_required
def stk_callback(request, uid):
    """
    STK Push result callback — Safaricom reports whether the user paid or cancelled.

    Payload structure:
        Body.stkCallback.ResultCode  (0 = success, non-zero = failure/cancellation)
        Body.stkCallback.CheckoutRequestID
        Body.stkCallback.CallbackMetadata.Item  (only present on success)
            - Amount, MpesaReceiptNumber, TransactionDate, PhoneNumber

    ResultCode 1032 = Request cancelled by user.
    """
    shortcode = _get_shortcode(uid)
    if not shortcode:
        logger.warning('STK callback for unknown/inactive shortcode uid=%s', uid)
        return JsonResponse(ACCEPTED)

    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error('STK callback received malformed JSON for shortcode uid=%s', uid)
        return JsonResponse(ACCEPTED)

    stk = payload.get('Body', {}).get('stkCallback', {})
    logger.info(
        'STK callback received: shortcode=%s CheckoutRequestID=%s ResultCode=%s',
        shortcode.shortcode_number,
        stk.get('CheckoutRequestID'),
        stk.get('ResultCode'),
    )

    try:
        handle_stk_callback(shortcode, payload)
    except Exception:
        logger.exception('Unhandled error in STK callback handler (shortcode=%s)', uid)
    return JsonResponse(ACCEPTED)
