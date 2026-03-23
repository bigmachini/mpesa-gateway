"""
Tests for the C2B validation flow.

Covers:
  - validate endpoint when validation is disabled (always ACCEPTED)
  - pre_register mode: valid reference, wrong amount, expired, already used, unknown ref
  - webhook mode: upstream accepts, upstream rejects, timeout/unreachable
  - ResponseType in register_c2b_urls changes based on enable_c2b_validation

Safaricom validate payload mirrors the C2B confirm payload structure.
"""
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import ClientFactory
from apps.shortcodes.models import PaymentReference
from apps.shortcodes.tests.factories import ShortcodeFactory

VALIDATE_PAYLOAD = {
    'TransactionType': 'Pay Bill',
    'TransID': 'LGR019G3J2',
    'TransTime': '20191122063845',
    'TransAmount': '100.00',
    'BusinessShortCode': '600638',
    'BillRefNumber': 'INV001',
    'InvoiceNumber': '',
    'OrgAccountBalance': '',
    'ThirdPartyTransID': '',
    'MSISDN': '254708374149',
    'FirstName': 'John',
    'MiddleName': '',
    'LastName': 'Doe',
}

ACCEPTED = {'ResultCode': 0, 'ResultDesc': 'Accepted'}
REJECTED = {'ResultCode': 1, 'ResultDesc': 'Rejected'}


def _post_validate(client, uid, payload):
    url = reverse('c2b-validate', kwargs={'uid': uid})
    return client.post(url, data=json.dumps(payload), content_type='application/json')


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client_user(db):
    return ClientFactory(is_active=True)


@pytest.fixture
def byoc_shortcode(db, client_user):
    return ShortcodeFactory(
        client=client_user,
        shortcode_type='paybill',
        tier='byoc',
        enable_c2b_validation=False,
    )


@pytest.fixture
def pre_register_shortcode(db, client_user):
    return ShortcodeFactory(
        client=client_user,
        shortcode_type='paybill',
        tier='byoc',
        enable_c2b_validation=True,
        validation_mode='pre_register',
    )


@pytest.fixture
def webhook_shortcode(db, client_user):
    return ShortcodeFactory(
        client=client_user,
        shortcode_type='paybill',
        tier='byoc',
        enable_c2b_validation=True,
        validation_mode='webhook',
        validation_webhook_url='https://client.example.com/validate/',
    )


def _make_reference(shortcode, reference='INV001', amount='100.00', minutes_until_expiry=60, is_used=False):
    return PaymentReference.objects.create(
        shortcode=shortcode,
        reference=reference,
        amount=Decimal(amount),
        expires_at=timezone.now() + timedelta(minutes=minutes_until_expiry),
        is_used=is_used,
    )


# ---------------------------------------------------------------------------
# Validation disabled — always accept
# ---------------------------------------------------------------------------

class TestValidationDisabled:
    def test_accepted_when_validation_disabled(self, client, byoc_shortcode):
        response = _post_validate(client, byoc_shortcode.uid, VALIDATE_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == ACCEPTED

    def test_accepted_for_unknown_uid(self, client, db):
        import uuid
        response = _post_validate(client, uuid.uuid4(), VALIDATE_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == ACCEPTED


# ---------------------------------------------------------------------------
# Pre-register mode
# ---------------------------------------------------------------------------

class TestPreRegisterValidation:
    def test_valid_reference_returns_accepted(self, client, pre_register_shortcode):
        _make_reference(pre_register_shortcode, reference='INV001', amount='100.00')
        response = _post_validate(client, pre_register_shortcode.uid, VALIDATE_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == ACCEPTED

    def test_valid_reference_is_marked_used(self, client, pre_register_shortcode):
        ref = _make_reference(pre_register_shortcode, reference='INV001', amount='100.00')
        _post_validate(client, pre_register_shortcode.uid, VALIDATE_PAYLOAD)
        ref.refresh_from_db()
        assert ref.is_used is True

    def test_unknown_reference_returns_rejected(self, client, pre_register_shortcode):
        # No PaymentReference created
        response = _post_validate(client, pre_register_shortcode.uid, VALIDATE_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == REJECTED

    def test_wrong_amount_returns_rejected(self, client, pre_register_shortcode):
        _make_reference(pre_register_shortcode, reference='INV001', amount='50.00')
        response = _post_validate(client, pre_register_shortcode.uid, VALIDATE_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == REJECTED

    def test_expired_reference_returns_rejected(self, client, pre_register_shortcode):
        _make_reference(pre_register_shortcode, reference='INV001', amount='100.00', minutes_until_expiry=-1)
        response = _post_validate(client, pre_register_shortcode.uid, VALIDATE_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == REJECTED

    def test_already_used_reference_returns_rejected(self, client, pre_register_shortcode):
        _make_reference(pre_register_shortcode, reference='INV001', amount='100.00', is_used=True)
        response = _post_validate(client, pre_register_shortcode.uid, VALIDATE_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == REJECTED

    def test_shared_paybill_strips_account_code_from_ref(self, client, client_user, db):
        shared_sc = ShortcodeFactory(
            client=client_user,
            shortcode_type='paybill',
            tier='shared',
            account_code='123456',
            shortcode_number='400200',
            enable_c2b_validation=True,
            validation_mode='pre_register',
        )
        _make_reference(shared_sc, reference='INV001', amount='100.00')
        payload = {**VALIDATE_PAYLOAD, 'BillRefNumber': '123456#INV001'}
        response = _post_validate(client, shared_sc.uid, payload)
        assert response.status_code == 200
        assert response.json() == ACCEPTED

    def test_malformed_json_returns_rejected(self, client, pre_register_shortcode):
        url = reverse('c2b-validate', kwargs={'uid': pre_register_shortcode.uid})
        response = client.post(url, data='not-json', content_type='application/json')
        assert response.status_code == 200
        assert response.json() == REJECTED


# ---------------------------------------------------------------------------
# Webhook mode
# ---------------------------------------------------------------------------

class TestWebhookValidation:
    @patch('apps.daraja.callbacks.httpx.Client')
    def test_upstream_accepts_returns_accepted(self, mock_client_cls, client, webhook_shortcode):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'ResultCode': 0, 'ResultDesc': 'Accepted'}
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        response = _post_validate(client, webhook_shortcode.uid, VALIDATE_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == ACCEPTED

    @patch('apps.daraja.callbacks.httpx.Client')
    def test_upstream_rejects_returns_rejected(self, mock_client_cls, client, webhook_shortcode):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'ResultCode': 1, 'ResultDesc': 'Unknown reference'}
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        response = _post_validate(client, webhook_shortcode.uid, VALIDATE_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == REJECTED

    @patch('apps.daraja.callbacks.httpx.Client')
    def test_upstream_timeout_returns_rejected(self, mock_client_cls, client, webhook_shortcode):
        import httpx
        mock_client_cls.return_value.__enter__.return_value.post.side_effect = httpx.TimeoutException('timeout')

        response = _post_validate(client, webhook_shortcode.uid, VALIDATE_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == REJECTED

    @patch('apps.daraja.callbacks.httpx.Client')
    def test_upstream_unreachable_returns_rejected(self, mock_client_cls, client, webhook_shortcode):
        import httpx
        mock_client_cls.return_value.__enter__.return_value.post.side_effect = httpx.ConnectError('unreachable')

        response = _post_validate(client, webhook_shortcode.uid, VALIDATE_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == REJECTED

    @patch('apps.daraja.callbacks.httpx.Client')
    def test_webhook_forwards_original_payload(self, mock_client_cls, client, webhook_shortcode):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'ResultCode': 0, 'ResultDesc': 'Accepted'}
        mock_post = mock_client_cls.return_value.__enter__.return_value.post
        mock_post.return_value = mock_resp

        _post_validate(client, webhook_shortcode.uid, VALIDATE_PAYLOAD)

        call_kwargs = mock_post.call_args
        forwarded = call_kwargs.kwargs.get('json') or call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
        if forwarded is None:
            forwarded = call_kwargs[1].get('json')
        assert forwarded is not None
        assert forwarded['TransID'] == VALIDATE_PAYLOAD['TransID']


# ---------------------------------------------------------------------------
# register_c2b_urls ResponseType
# ---------------------------------------------------------------------------

class TestRegisterC2BResponseType:
    @patch('apps.daraja.c2b.httpx.Client')
    @patch('apps.daraja.c2b.get_access_token', return_value='test-token')
    def test_response_type_completed_when_validation_disabled(
        self, _mock_token, mock_client_cls, db, client_user
    ):
        sc = ShortcodeFactory(client=client_user, enable_c2b_validation=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'ResponseCode': '0'}
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        from apps.daraja.c2b import register_c2b_urls
        register_c2b_urls(sc)

        call_kwargs = mock_client_cls.return_value.__enter__.return_value.post.call_args
        sent_payload = call_kwargs.kwargs.get('json') or call_kwargs[1]['json']
        assert sent_payload['ResponseType'] == 'Completed'

    @patch('apps.daraja.c2b.httpx.Client')
    @patch('apps.daraja.c2b.get_access_token', return_value='test-token')
    def test_response_type_cancelled_when_validation_enabled(
        self, _mock_token, mock_client_cls, db, client_user
    ):
        sc = ShortcodeFactory(
            client=client_user,
            enable_c2b_validation=True,
            validation_mode='pre_register',
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {'ResponseCode': '0'}
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_resp

        from apps.daraja.c2b import register_c2b_urls
        register_c2b_urls(sc)

        call_kwargs = mock_client_cls.return_value.__enter__.return_value.post.call_args
        sent_payload = call_kwargs.kwargs.get('json') or call_kwargs[1]['json']
        assert sent_payload['ResponseType'] == 'Cancelled'
