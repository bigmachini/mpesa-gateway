"""
Tests for Safaricom callback views.

Safaricom sends plain POST requests with no auth headers.
These views must always return HTTP 200 + {"ResultCode": 0, "ResultDesc": "Accepted"}.

Sandbox vs production payload note:
  - Sandbox C2B payloads use string amounts ("10.00"); production may send numeric.
  - STK callback metadata Items use mixed types (string names, numeric/string values).
  All tests use sandbox-style payloads as that is the primary integration environment.
"""
import json
import uuid
from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import ClientFactory
from apps.shortcodes.tests.factories import ShortcodeFactory

ACCEPTED = {'ResultCode': 0, 'ResultDesc': 'Accepted'}

# ---------------------------------------------------------------------------
# Realistic Safaricom payload fixtures
# ---------------------------------------------------------------------------

C2B_VALIDATE_PAYLOAD = {
    'TransactionType': 'Pay Bill',
    'TransID': 'LGR019G3J2',
    'TransTime': '20191122063845',
    'TransAmount': '10.00',
    'BusinessShortCode': '600638',
    'BillRefNumber': 'account',
    'InvoiceNumber': '',
    'OrgAccountBalance': '',
    'ThirdPartyTransID': '',
    'MSISDN': '254708374149',
    'FirstName': 'John',
    'MiddleName': '',
    'LastName': 'Doe',
}

C2B_CONFIRM_PAYLOAD = {
    **C2B_VALIDATE_PAYLOAD,
    'OrgAccountBalance': '49197.00',
}

STK_CALLBACK_SUCCESS = {
    'Body': {
        'stkCallback': {
            'MerchantRequestID': '29115-34620561-1',
            'CheckoutRequestID': 'ws_CO_191220191020363925',
            'ResultCode': 0,
            'ResultDesc': 'The service request is processed successfully.',
            'CallbackMetadata': {
                'Item': [
                    {'Name': 'Amount', 'Value': 1.00},
                    {'Name': 'MpesaReceiptNumber', 'Value': 'NLJ7RT61SV'},
                    {'Name': 'TransactionDate', 'Value': 20191219102115},
                    {'Name': 'PhoneNumber', 'Value': 254708374149},
                ]
            },
        }
    }
}

STK_CALLBACK_CANCELLED = {
    'Body': {
        'stkCallback': {
            'MerchantRequestID': '29115-34620561-1',
            'CheckoutRequestID': 'ws_CO_191220191020363925',
            'ResultCode': 1032,
            'ResultDesc': 'Request cancelled by user.',
        }
    }
}


@pytest.fixture
def client_user(db):
    return ClientFactory(is_active=True)


@pytest.fixture
def byoc_shortcode(db, client_user):
    return ShortcodeFactory(
        client=client_user,
        shortcode_type='paybill',
        tier='byoc',
    )


@pytest.fixture
def shared_shortcode(db, client_user):
    return ShortcodeFactory(
        client=client_user,
        shortcode_type='paybill',
        tier='shared',
        account_code='123456',
        shortcode_number='400200',
    )


def _post(client, url_name, uid, payload):
    url = reverse(url_name, kwargs={'uid': uid})
    return client.post(
        url,
        data=json.dumps(payload),
        content_type='application/json',
    )


# ---------------------------------------------------------------------------
# C2B Validate
# ---------------------------------------------------------------------------

class TestC2BValidate:
    def test_valid_uid_returns_accepted(self, client, byoc_shortcode):
        response = _post(client, 'c2b-validate', byoc_shortcode.uid, C2B_VALIDATE_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == ACCEPTED

    def test_unknown_uid_still_returns_accepted(self, client, db):
        """Safaricom must always get 200; never expose 404 to them."""
        response = _post(client, 'c2b-validate', uuid.uuid4(), C2B_VALIDATE_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == ACCEPTED

    def test_inactive_shortcode_still_returns_accepted(self, client, byoc_shortcode):
        byoc_shortcode.is_active = False
        byoc_shortcode.save()
        response = _post(client, 'c2b-validate', byoc_shortcode.uid, C2B_VALIDATE_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == ACCEPTED


# ---------------------------------------------------------------------------
# C2B Confirm
# ---------------------------------------------------------------------------

class TestC2BConfirm:
    @patch('apps.daraja.callbacks.handle_c2b_confirmation')
    def test_valid_payload_calls_handler_and_returns_accepted(
        self, mock_handler, client, byoc_shortcode
    ):
        response = _post(client, 'c2b-confirm', byoc_shortcode.uid, C2B_CONFIRM_PAYLOAD)

        assert response.status_code == 200
        assert response.json() == ACCEPTED
        mock_handler.assert_called_once_with(byoc_shortcode, C2B_CONFIRM_PAYLOAD)

    @patch('apps.daraja.callbacks.handle_c2b_confirmation')
    def test_unknown_uid_returns_accepted_without_calling_handler(
        self, mock_handler, client, db
    ):
        response = _post(client, 'c2b-confirm', uuid.uuid4(), C2B_CONFIRM_PAYLOAD)
        assert response.status_code == 200
        assert response.json() == ACCEPTED
        mock_handler.assert_not_called()

    @patch('apps.daraja.callbacks.handle_c2b_confirmation')
    def test_malformed_json_returns_accepted(self, mock_handler, client, byoc_shortcode):
        url = reverse('c2b-confirm', kwargs={'uid': byoc_shortcode.uid})
        response = client.post(url, data='not-json', content_type='application/json')
        assert response.status_code == 200
        assert response.json() == ACCEPTED
        mock_handler.assert_not_called()

    @patch('apps.daraja.callbacks.handle_c2b_confirmation')
    def test_handler_exception_still_returns_accepted(
        self, mock_handler, client, byoc_shortcode
    ):
        """Daraja callback must return 200 even if our handler crashes."""
        mock_handler.side_effect = Exception('DB down')
        response = _post(client, 'c2b-confirm', byoc_shortcode.uid, C2B_CONFIRM_PAYLOAD)
        # callbacks.py calls handle_c2b_confirmation which wraps in try/except inside handlers.py
        # The view itself doesn't catch — handler exceptions are swallowed in handlers.py
        assert response.status_code == 200

    @patch('apps.daraja.callbacks.handle_c2b_confirmation')
    def test_shared_paybill_shortcode_routes_correctly(
        self, mock_handler, client, shared_shortcode
    ):
        payload = {**C2B_CONFIRM_PAYLOAD, 'BillRefNumber': '123456#INV001'}
        response = _post(client, 'c2b-confirm', shared_shortcode.uid, payload)
        assert response.status_code == 200
        mock_handler.assert_called_once_with(shared_shortcode, payload)


# ---------------------------------------------------------------------------
# STK Callback
# ---------------------------------------------------------------------------

class TestSTKCallback:
    @patch('apps.daraja.callbacks.handle_stk_callback')
    def test_success_callback_calls_handler_and_returns_accepted(
        self, mock_handler, client, byoc_shortcode
    ):
        response = _post(client, 'stk-callback', byoc_shortcode.uid, STK_CALLBACK_SUCCESS)
        assert response.status_code == 200
        assert response.json() == ACCEPTED
        mock_handler.assert_called_once_with(byoc_shortcode, STK_CALLBACK_SUCCESS)

    @patch('apps.daraja.callbacks.handle_stk_callback')
    def test_cancelled_callback_calls_handler_and_returns_accepted(
        self, mock_handler, client, byoc_shortcode
    ):
        response = _post(client, 'stk-callback', byoc_shortcode.uid, STK_CALLBACK_CANCELLED)
        assert response.status_code == 200
        assert response.json() == ACCEPTED
        mock_handler.assert_called_once()

    @patch('apps.daraja.callbacks.handle_stk_callback')
    def test_unknown_uid_returns_accepted_without_calling_handler(
        self, mock_handler, client, db
    ):
        response = _post(client, 'stk-callback', uuid.uuid4(), STK_CALLBACK_SUCCESS)
        assert response.status_code == 200
        assert response.json() == ACCEPTED
        mock_handler.assert_not_called()

    @patch('apps.daraja.callbacks.handle_stk_callback')
    def test_malformed_json_returns_accepted(self, mock_handler, client, byoc_shortcode):
        url = reverse('stk-callback', kwargs={'uid': byoc_shortcode.uid})
        response = client.post(url, data='bad-json', content_type='application/json')
        assert response.status_code == 200
        assert response.json() == ACCEPTED
        mock_handler.assert_not_called()


# ---------------------------------------------------------------------------
# IP filtering
# ---------------------------------------------------------------------------

class TestIPFilter:
    @patch('apps.daraja.callbacks.handle_c2b_confirmation')
    def test_non_safaricom_ip_blocked_when_restriction_enabled(
        self, mock_handler, client, byoc_shortcode, settings
    ):
        settings.DARAJA_RESTRICT_CALLBACK_IPS = True
        response = client.post(
            reverse('c2b-confirm', kwargs={'uid': byoc_shortcode.uid}),
            data=json.dumps(C2B_CONFIRM_PAYLOAD),
            content_type='application/json',
            REMOTE_ADDR='1.2.3.4',
        )
        assert response.status_code == 403
        mock_handler.assert_not_called()

    @patch('apps.daraja.callbacks.handle_c2b_confirmation')
    def test_safaricom_ip_allowed_when_restriction_enabled(
        self, mock_handler, client, byoc_shortcode, settings
    ):
        settings.DARAJA_RESTRICT_CALLBACK_IPS = True
        response = client.post(
            reverse('c2b-confirm', kwargs={'uid': byoc_shortcode.uid}),
            data=json.dumps(C2B_CONFIRM_PAYLOAD),
            content_type='application/json',
            REMOTE_ADDR='196.201.214.200',  # known Safaricom IP
        )
        assert response.status_code == 200
        mock_handler.assert_called_once()

    @patch('apps.daraja.callbacks.handle_c2b_confirmation')
    def test_any_ip_allowed_when_restriction_disabled(
        self, mock_handler, client, byoc_shortcode, settings
    ):
        settings.DARAJA_RESTRICT_CALLBACK_IPS = False
        response = client.post(
            reverse('c2b-confirm', kwargs={'uid': byoc_shortcode.uid}),
            data=json.dumps(C2B_CONFIRM_PAYLOAD),
            content_type='application/json',
            REMOTE_ADDR='127.0.0.1',
        )
        assert response.status_code == 200
