"""
Tests for Daraja OAuth token management.
"""
from unittest.mock import MagicMock, patch

import pytest

from apps.accounts.tests.factories import ClientFactory
from apps.shortcodes.tests.factories import ShortcodeFactory
from apps.daraja.auth import get_access_token, invalidate_token, CACHE_KEY_PREFIX


@pytest.fixture
def client_user(db):
    return ClientFactory(is_active=True)


@pytest.fixture
def byoc_shortcode(db, client_user):
    return ShortcodeFactory(
        client=client_user,
        tier='byoc',
        shortcode_type='paybill',
        consumer_key='test-ck',
        consumer_secret='test-cs',
    )


@pytest.fixture
def shared_shortcode(db, client_user):
    return ShortcodeFactory(
        client=client_user,
        tier='shared',
        shortcode_type='paybill',
        shortcode_number='400200',
        account_code='123456',
    )


class TestGetAccessToken:
    def test_returns_cached_token_without_calling_daraja(self, byoc_shortcode):
        cache_key = f'{CACHE_KEY_PREFIX}{byoc_shortcode.uid}'
        with patch('apps.daraja.auth.cache') as mock_cache:
            mock_cache.get.return_value = 'cached-token-abc'
            token = get_access_token(byoc_shortcode)

        assert token == 'cached-token-abc'
        mock_cache.get.assert_called_once_with(cache_key)

    def test_fetches_token_from_daraja_on_cache_miss(self, byoc_shortcode):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'access_token': 'fresh-token-xyz',
            'expires_in': '3600',
        }

        with patch('apps.daraja.auth.cache') as mock_cache, \
             patch('apps.daraja.auth.httpx.Client') as mock_client_cls:
            mock_cache.get.return_value = None
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_response

            token = get_access_token(byoc_shortcode)

        assert token == 'fresh-token-xyz'
        # Token must be cached with TTL = expires_in - 60 = 3540
        mock_cache.set.assert_called_once_with(
            f'{CACHE_KEY_PREFIX}{byoc_shortcode.uid}',
            'fresh-token-xyz',
            3540,
        )

    def test_byoc_shortcode_uses_own_credentials(self, byoc_shortcode, settings):
        settings.DARAJA_CONSUMER_KEY = 'platform-ck'
        settings.DARAJA_CONSUMER_SECRET = 'platform-cs'

        mock_response = MagicMock()
        mock_response.json.return_value = {'access_token': 'tok', 'expires_in': '3600'}

        with patch('apps.daraja.auth.cache') as mock_cache, \
             patch('apps.daraja.auth.httpx.Client') as mock_client_cls:
            mock_cache.get.return_value = None
            mock_get = mock_client_cls.return_value.__enter__.return_value.get
            mock_get.return_value = mock_response

            get_access_token(byoc_shortcode)

            call_kwargs = mock_get.call_args
            auth_header = call_kwargs[1]['headers']['Authorization']

        import base64
        encoded = base64.b64encode(b'test-ck:test-cs').decode()
        assert auth_header == f'Basic {encoded}'

    def test_shared_shortcode_uses_platform_credentials(self, shared_shortcode, settings):
        settings.DARAJA_CONSUMER_KEY = 'platform-ck'
        settings.DARAJA_CONSUMER_SECRET = 'platform-cs'

        mock_response = MagicMock()
        mock_response.json.return_value = {'access_token': 'tok', 'expires_in': '3600'}

        with patch('apps.daraja.auth.cache') as mock_cache, \
             patch('apps.daraja.auth.httpx.Client') as mock_client_cls:
            mock_cache.get.return_value = None
            mock_get = mock_client_cls.return_value.__enter__.return_value.get
            mock_get.return_value = mock_response

            get_access_token(shared_shortcode)

            call_kwargs = mock_get.call_args
            auth_header = call_kwargs[1]['headers']['Authorization']

        import base64
        encoded = base64.b64encode(b'platform-ck:platform-cs').decode()
        assert auth_header == f'Basic {encoded}'


class TestInvalidateToken:
    def test_removes_token_from_cache(self, byoc_shortcode):
        with patch('apps.daraja.auth.cache') as mock_cache:
            invalidate_token(byoc_shortcode)
            mock_cache.delete.assert_called_once_with(
                f'{CACHE_KEY_PREFIX}{byoc_shortcode.uid}'
            )
