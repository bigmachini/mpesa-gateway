"""
Payment event handlers called from Safaricom callback views.

These are thin dispatchers — all business logic lives in transactions.services.
"""
import logging

from apps.transactions.services import record_c2b_transaction, record_stk_callback

logger = logging.getLogger(__name__)


def handle_c2b_confirmation(shortcode, payload: dict) -> None:
    """
    Called when a C2B confirmation arrives from Safaricom.
    Records the transaction, credits wallet (Shared Paybill), dispatches webhook.
    """
    try:
        record_c2b_transaction(shortcode, payload)
    except Exception:
        logger.exception(
            'Error recording C2B transaction (shortcode=%s, TransID=%s)',
            shortcode.uid, payload.get('TransID'),
        )


def handle_stk_callback(shortcode, payload: dict) -> None:
    """
    Called when an STK Push result arrives from Safaricom.
    Updates the pending Transaction status, credits wallet on success,
    dispatches webhook.
    """
    stk = payload.get('Body', {}).get('stkCallback', {})
    checkout_id = stk.get('CheckoutRequestID', 'unknown')
    try:
        record_stk_callback(shortcode, payload)
    except Exception:
        logger.exception(
            'Error handling STK callback (shortcode=%s, CheckoutRequestID=%s)',
            shortcode.uid, checkout_id,
        )
