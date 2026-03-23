import base64
import hashlib
import logging
from datetime import datetime
from functools import wraps

from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger(__name__)

# Safaricom production IP ranges (keep up-to-date from Safaricom docs)
SAFARICOM_IPS = {
    '196.201.214.200', '196.201.214.206', '196.201.213.114',
    '196.201.214.207', '196.201.214.208', '196.201.213.44',
    '196.201.212.127', '196.201.212.138', '196.201.212.129',
    '196.201.212.136', '196.201.212.74', '196.201.212.69',
}


def get_timestamp() -> str:
    """Return current timestamp in Daraja format: YYYYMMDDHHmmss."""
    return datetime.now().strftime('%Y%m%d%H%M%S')


def get_stk_password(shortcode, timestamp: str) -> str:
    """
    Generate the STK Push password.
    Formula: base64(shortcode_number + passkey + timestamp)
    """
    if shortcode.tier == 'shared':
        shortcode_number = settings.DARAJA_SHORTCODE
        passkey = settings.DARAJA_PASSKEY
    else:
        shortcode_number = shortcode.shortcode_number
        passkey = shortcode.passkey

    raw = f'{shortcode_number}{passkey}{timestamp}'
    return base64.b64encode(raw.encode()).decode()


def get_client_ip(request) -> str:
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


def safaricom_ip_required(view_func):
    """
    Decorator that restricts a view to Safaricom IP ranges in production.
    In DEBUG mode all IPs are allowed so sandbox testing works locally.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if getattr(settings, 'DARAJA_RESTRICT_CALLBACK_IPS', True):
            ip = get_client_ip(request)
            if ip not in SAFARICOM_IPS:
                logger.warning('Blocked callback from non-Safaricom IP: %s', ip)
                return JsonResponse({'ResultCode': 1, 'ResultDesc': 'Forbidden'}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper
