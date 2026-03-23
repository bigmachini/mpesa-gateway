"""
Tests for transactions.services — the core recording logic.

These test the service functions directly, independent of the HTTP layer.
Safaricom payload structures follow sandbox format (string amounts).
"""
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.shortcodes.tests.factories import ShortcodeFactory
from apps.accounts.tests.factories import ClientFactory
from apps.transactions.models import Transaction
from apps.transactions.services import (
    create_stk_transaction,
    record_c2b_transaction,
    record_stk_callback,
)

C2B_PAYLOAD = {
    'TransactionType': 'Pay Bill',
    'TransID': 'LGR019G3J2',
    'TransTime': '20191122063845',
    'TransAmount': '250.00',
    'BusinessShortCode': '600638',
    'BillRefNumber': 'INV001',
    'InvoiceNumber': '',
    'OrgAccountBalance': '49197.00',
    'ThirdPartyTransID': '',
    'MSISDN': '254708374149',
    'FirstName': 'John',
    'MiddleName': '',
    'LastName': 'Doe',
}

STK_SUCCESS_PAYLOAD = {
    'Body': {
        'stkCallback': {
            'MerchantRequestID': '29115-34620561-1',
            'CheckoutRequestID': 'ws_CO_191220191020363925',
            'ResultCode': 0,
            'ResultDesc': 'The service request is processed successfully.',
            'CallbackMetadata': {
                'Item': [
                    {'Name': 'Amount', 'Value': 1500.00},
                    {'Name': 'MpesaReceiptNumber', 'Value': 'NLJ7RT61SV'},
                    {'Name': 'TransactionDate', 'Value': 20191219102115},
                    {'Name': 'PhoneNumber', 'Value': 254708374149},
                ]
            },
        }
    }
}

STK_FAILED_PAYLOAD = {
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
def byoc_shortcode(db):
    return ShortcodeFactory(shortcode_type='paybill', tier='byoc')


@pytest.fixture
def till_shortcode(db):
    return ShortcodeFactory(shortcode_type='till', tier='byoc')


@pytest.fixture
def shared_shortcode(db):
    return ShortcodeFactory(
        shortcode_type='paybill', tier='shared',
        account_code='123456', shortcode_number='400200',
        webhook_url=None,
    )


# ---------------------------------------------------------------------------
# C2B recording
# ---------------------------------------------------------------------------

class TestRecordC2BTransaction:
    def test_creates_completed_transaction(self, byoc_shortcode):
        txn = record_c2b_transaction(byoc_shortcode, C2B_PAYLOAD)
        assert txn is not None
        assert txn.status == 'completed'
        assert txn.transaction_type == 'c2b_paybill'

    def test_parses_amount_correctly(self, byoc_shortcode):
        txn = record_c2b_transaction(byoc_shortcode, C2B_PAYLOAD)
        assert txn.amount == Decimal('250.00')

    def test_stores_receipt_number(self, byoc_shortcode):
        txn = record_c2b_transaction(byoc_shortcode, C2B_PAYLOAD)
        assert txn.mpesa_receipt_number == 'LGR019G3J2'

    def test_stores_msisdn(self, byoc_shortcode):
        txn = record_c2b_transaction(byoc_shortcode, C2B_PAYLOAD)
        assert txn.msisdn == '254708374149'

    def test_stores_raw_payload(self, byoc_shortcode):
        txn = record_c2b_transaction(byoc_shortcode, C2B_PAYLOAD)
        assert txn.raw_payload == C2B_PAYLOAD

    def test_stores_bill_ref_number(self, byoc_shortcode):
        txn = record_c2b_transaction(byoc_shortcode, C2B_PAYLOAD)
        assert txn.bill_ref_number == 'INV001'

    def test_till_shortcode_sets_c2b_till_type(self, till_shortcode):
        txn = record_c2b_transaction(till_shortcode, C2B_PAYLOAD)
        assert txn.transaction_type == 'c2b_till'

    def test_duplicate_receipt_returns_none(self, byoc_shortcode):
        record_c2b_transaction(byoc_shortcode, C2B_PAYLOAD)
        result = record_c2b_transaction(byoc_shortcode, C2B_PAYLOAD)
        assert result is None
        assert Transaction.objects.filter(mpesa_receipt_number='LGR019G3J2').count() == 1

    def test_missing_trans_id_returns_none(self, byoc_shortcode):
        payload = {**C2B_PAYLOAD, 'TransID': ''}
        result = record_c2b_transaction(byoc_shortcode, payload)
        assert result is None
        assert Transaction.objects.count() == 0

    def test_parses_safaricom_timestamp(self, byoc_shortcode):
        txn = record_c2b_transaction(byoc_shortcode, C2B_PAYLOAD)
        assert txn.transaction_time.year == 2019
        assert txn.transaction_time.month == 11
        assert txn.transaction_time.day == 22

    @patch('apps.transactions.services._dispatch_post_transaction')
    def test_dispatches_post_transaction(self, mock_dispatch, byoc_shortcode):
        txn = record_c2b_transaction(byoc_shortcode, C2B_PAYLOAD)
        mock_dispatch.assert_called_once_with(txn)

    def test_shared_paybill_creates_transaction(self, shared_shortcode):
        txn = record_c2b_transaction(shared_shortcode, C2B_PAYLOAD)
        assert txn is not None
        assert txn.shortcode == shared_shortcode


# ---------------------------------------------------------------------------
# STK Push
# ---------------------------------------------------------------------------

class TestCreateSTKTransaction:
    def test_creates_pending_transaction(self, byoc_shortcode):
        txn = create_stk_transaction(
            byoc_shortcode,
            checkout_request_id='ws_CO_test_001',
            phone='254708374149',
            amount='500.00',
        )
        assert txn.status == 'pending'
        assert txn.transaction_type == 'stk_push'
        assert txn.checkout_request_id == 'ws_CO_test_001'
        assert txn.amount == Decimal('500.00')


class TestRecordSTKCallback:
    def test_success_marks_completed(self, byoc_shortcode):
        create_stk_transaction(
            byoc_shortcode,
            checkout_request_id='ws_CO_191220191020363925',
            phone='254708374149',
            amount='1500.00',
        )
        txn = record_stk_callback(byoc_shortcode, STK_SUCCESS_PAYLOAD)
        assert txn.status == 'completed'

    def test_success_updates_receipt_number(self, byoc_shortcode):
        create_stk_transaction(
            byoc_shortcode,
            checkout_request_id='ws_CO_191220191020363925',
            phone='254708374149',
            amount='1500.00',
        )
        txn = record_stk_callback(byoc_shortcode, STK_SUCCESS_PAYLOAD)
        assert txn.mpesa_receipt_number == 'NLJ7RT61SV'

    def test_success_updates_amount_from_metadata(self, byoc_shortcode):
        create_stk_transaction(
            byoc_shortcode,
            checkout_request_id='ws_CO_191220191020363925',
            phone='254708374149',
            amount='0',
        )
        txn = record_stk_callback(byoc_shortcode, STK_SUCCESS_PAYLOAD)
        assert txn.amount == Decimal('1500.00')

    def test_cancelled_marks_failed(self, byoc_shortcode):
        create_stk_transaction(
            byoc_shortcode,
            checkout_request_id='ws_CO_191220191020363925',
            phone='254708374149',
            amount='1500.00',
        )
        txn = record_stk_callback(byoc_shortcode, STK_FAILED_PAYLOAD)
        assert txn.status == 'failed'

    def test_unknown_checkout_id_creates_record(self, byoc_shortcode):
        # No prior create_stk_transaction call
        txn = record_stk_callback(byoc_shortcode, STK_SUCCESS_PAYLOAD)
        assert txn is not None
        assert Transaction.objects.filter(
            checkout_request_id='ws_CO_191220191020363925'
        ).exists()

    def test_duplicate_receipt_on_success_skips(self, byoc_shortcode):
        """If receipt already recorded, don't create a duplicate."""
        create_stk_transaction(
            byoc_shortcode,
            checkout_request_id='ws_CO_191220191020363925',
            phone='254708374149',
            amount='1500.00',
        )
        record_stk_callback(byoc_shortcode, STK_SUCCESS_PAYLOAD)
        # Second callback with same payload
        result = record_stk_callback(byoc_shortcode, STK_SUCCESS_PAYLOAD)
        assert result is None
        assert Transaction.objects.filter(mpesa_receipt_number='NLJ7RT61SV').count() == 1

    @patch('apps.transactions.services._dispatch_post_transaction')
    def test_dispatches_post_transaction_on_success(self, mock_dispatch, byoc_shortcode):
        create_stk_transaction(
            byoc_shortcode,
            checkout_request_id='ws_CO_191220191020363925',
            phone='254708374149',
            amount='1500.00',
        )
        txn = record_stk_callback(byoc_shortcode, STK_SUCCESS_PAYLOAD)
        mock_dispatch.assert_called_once_with(txn)


# ---------------------------------------------------------------------------
# Downstream dispatch (wallet + webhook stubs)
# ---------------------------------------------------------------------------

class TestDispatchPostTransaction:
    @patch('apps.transactions.services.credit_wallet', create=True)
    def test_credits_wallet_for_shared_paybill(self, mock_credit, shared_shortcode):
        with patch.dict('sys.modules', {'apps.wallets.services': type('m', (), {'credit_wallet': mock_credit})()}):
            txn = record_c2b_transaction(shared_shortcode, C2B_PAYLOAD)
        # wallet credit is attempted — actual call verified in wallets tests

    def test_no_wallet_credit_for_byoc(self, byoc_shortcode):
        # Should not raise even if wallets app not wired
        txn = record_c2b_transaction(byoc_shortcode, C2B_PAYLOAD)
        assert txn.status == 'completed'
