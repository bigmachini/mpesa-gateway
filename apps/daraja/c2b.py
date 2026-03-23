import logging

import httpx
from django.conf import settings

from .auth import get_access_token, invalidate_token

logger = logging.getLogger(__name__)


def register_c2b_urls(shortcode) -> dict:
    """
    Register C2B validation and confirmation callback URLs with Safaricom.
    Must be called once per shortcode before going live.
    Returns the raw Daraja response dict.
    """
    token = get_access_token(shortcode)
    urls = shortcode.get_callback_urls()

    shortcode_number = (
        settings.DARAJA_SHORTCODE if shortcode.tier == 'shared'
        else shortcode.shortcode_number
    )

    # 'Cancelled' tells Safaricom to honour our validation response (accept/reject).
    # 'Completed' means Safaricom ignores our response and always confirms the payment.
    response_type = 'Cancelled' if shortcode.enable_c2b_validation else 'Completed'

    payload = {
        'ShortCode': shortcode_number,
        'ResponseType': response_type,
        'ConfirmationURL': urls['c2b_confirmation'],
        'ValidationURL': urls['c2b_validation'],
    }

    url = f'{settings.DARAJA_BASE_URL}/mpesa/c2b/v1/registerurl'

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
        logger.info('C2B URLs registered for shortcode %s: %s', shortcode.uid, result)
        return result

    except httpx.HTTPError as exc:
        logger.error('C2B URL registration failed for %s: %s', shortcode.uid, exc)
        raise
