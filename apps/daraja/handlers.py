"""
Payment event handlers called from Safaricom callback views.

These delegate to the transactions app (record_c2b_transaction,
record_stk_callback) which is wired up when that app is built.
The try/except ImportError pattern keeps daraja independently testable
before those apps exist.
"""
import logging

logger = logging.getLogger(__name__)


def handle_c2b_confirmation(shortcode, payload: dict) -> None:
    """
    Called when a C2B confirmation arrives from Safaricom.
    Records the transaction, credits wallet (Shared Paybill), dispatches webhook.
    """
    try:
        from apps.transactions.services import record_c2b_transaction
        record_c2b_transaction(shortcode, payload)
    except ImportError:
        logger.warning(
            'transactions.services not available; C2B transaction not recorded '
            '(shortcode=%s, TransID=%s)',
            shortcode.uid, payload.get('TransID'),
        )
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
        from apps.transactions.services import record_stk_callback
        record_stk_callback(shortcode, payload)
    except ImportError:
        logger.warning(
            'transactions.services not available; STK callback not handled '
            '(shortcode=%s, CheckoutRequestID=%s)',
            shortcode.uid, checkout_id,
        )
    except Exception:
        logger.exception(
            'Error handling STK callback (shortcode=%s, CheckoutRequestID=%s)',
            shortcode.uid, checkout_id,
        )
