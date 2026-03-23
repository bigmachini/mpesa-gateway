import logging

import httpx
from django.conf import settings

from .auth import get_access_token, invalidate_token
from .utils import get_timestamp, get_stk_password

logger = logging.getLogger(__name__)


def initiate_stk_push(
    shortcode,
    phone: str,
    amount: int,
    account_ref: str,
    description: str,
) -> dict:
    """
    Initiate an STK Push (Lipa na M-Pesa Online) request.

    Works for both BYOC and Shared Paybill clients.
    - BYOC: uses the shortcode's own credentials and shortcode_number.
    - Shared Paybill: uses platform credentials; account_ref should encode
      the client's account_code so the callback can route to the right wallet.

    Returns the raw Daraja response dict.
    Raises httpx.HTTPError on API failure.
    """
    token = get_access_token(shortcode)
    timestamp = get_timestamp()
    password = get_stk_password(shortcode, timestamp)

    shortcode_number = (
        settings.DARAJA_SHORTCODE if shortcode.tier == 'shared'
        else shortcode.shortcode_number
    )
    callback_url = shortcode.get_callback_urls()['stk_callback']

    payload = {
        'BusinessShortCode': shortcode_number,
        'Password': password,
        'Timestamp': timestamp,
        'TransactionType': 'CustomerPayBillOnline',
        'Amount': amount,
        'PartyA': phone,
        'PartyB': shortcode_number,
        'PhoneNumber': phone,
        'CallBackURL': callback_url,
        'AccountReference': account_ref,
        'TransactionDesc': description,
    }

    url = f'{settings.DARAJA_BASE_URL}/mpesa/stkpush/v1/processrequest'

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                url,
                json=payload,
                headers={'Authorization': f'Bearer {token}'},
            )

        if response.status_code == 401:
            invalidate_token(shortcode)
            raise ValueError('Daraja token rejected (401) — token invalidated, retry.')

        response.raise_for_status()
        result = response.json()
        logger.info('STK Push initiated for shortcode %s: %s', shortcode.uid, result.get('CheckoutRequestID'))
        return result

    except httpx.HTTPError as exc:
        logger.error('STK Push failed for shortcode %s: %s', shortcode.uid, exc)
        raise


def query_stk_status(shortcode, checkout_request_id: str) -> dict:
    """
    Query the status of a pending STK Push request.
    Returns the raw Daraja response dict.
    """
    token = get_access_token(shortcode)
    timestamp = get_timestamp()
    password = get_stk_password(shortcode, timestamp)

    shortcode_number = (
        settings.DARAJA_SHORTCODE if shortcode.tier == 'shared'
        else shortcode.shortcode_number
    )

    payload = {
        'BusinessShortCode': shortcode_number,
        'Password': password,
        'Timestamp': timestamp,
        'CheckoutRequestID': checkout_request_id,
    }

    url = f'{settings.DARAJA_BASE_URL}/mpesa/stkpushquery/v1/query'

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                url,
                json=payload,
                headers={'Authorization': f'Bearer {token}'},
            )

        if response.status_code == 401:
            invalidate_token(shortcode)
            raise ValueError('Daraja token rejected (401) — token invalidated, retry.')

        response.raise_for_status()
        return response.json()

    except httpx.HTTPError as exc:
        logger.error('STK status query failed for %s: %s', checkout_request_id, exc)
        raise
