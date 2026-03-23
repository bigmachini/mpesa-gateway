import base64
import logging

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_KEY_PREFIX = 'daraja:token:'


def _cache_key(shortcode) -> str:
    return f'{CACHE_KEY_PREFIX}{shortcode.uid}'


def _fetch_token(consumer_key: str, consumer_secret: str) -> tuple[str, int]:
    """Call the Daraja OAuth endpoint and return (access_token, ttl_seconds)."""
    credentials = base64.b64encode(f'{consumer_key}:{consumer_secret}'.encode()).decode()
    url = f'{settings.DARAJA_BASE_URL}/oauth/v1/generate?grant_type=client_credentials'

    with httpx.Client(timeout=15) as client:
        response = client.get(url, headers={'Authorization': f'Basic {credentials}'})
        response.raise_for_status()

    data = response.json()
    token = data['access_token']
    ttl = max(int(data.get('expires_in', 3600)) - 60, 30)
    return token, ttl


def get_access_token(shortcode) -> str:
    """
    Return a valid Daraja access token for the given shortcode.
    Checks Redis first; fetches from Daraja OAuth on cache miss.
    Cache key: daraja:token:<shortcode_uid>
    """
    key = _cache_key(shortcode)
    cached = cache.get(key)
    if cached:
        return cached

    if shortcode.tier == 'shared':
        consumer_key = settings.DARAJA_CONSUMER_KEY
        consumer_secret = settings.DARAJA_CONSUMER_SECRET
    else:
        consumer_key = shortcode.consumer_key
        consumer_secret = shortcode.consumer_secret

    token, ttl = _fetch_token(consumer_key, consumer_secret)
    cache.set(key, token, ttl)
    logger.debug('Fetched new Daraja token for shortcode %s (ttl=%ss)', shortcode.uid, ttl)
    return token


def invalidate_token(shortcode) -> None:
    """Remove a cached token (e.g. after a 401 response)."""
    cache.delete(_cache_key(shortcode))
