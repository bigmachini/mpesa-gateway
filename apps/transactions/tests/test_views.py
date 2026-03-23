"""
Tests for the transactions API (read-only list, detail, summary).
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.tests.factories import ClientFactory
from apps.shortcodes.tests.factories import ShortcodeFactory
from apps.transactions.tests.factories import TransactionFactory


@pytest.fixture
def auth_client(db):
    user = ClientFactory(is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    client._user = user
    return client


@pytest.fixture
def shortcode(db, auth_client):
    return ShortcodeFactory(client=auth_client._user)


@pytest.fixture
def other_shortcode(db):
    return ShortcodeFactory()


LIST_URL = reverse('transaction-list')
SUMMARY_URL = reverse('transaction-summary')


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestTransactionAuth:
    def test_unauthenticated_list_rejected(self, db):
        resp = APIClient().get(LIST_URL)
        assert resp.status_code == 401

    def test_unauthenticated_summary_rejected(self, db):
        resp = APIClient().get(SUMMARY_URL)
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestTransactionList:
    def test_returns_own_transactions(self, auth_client, shortcode):
        TransactionFactory(shortcode=shortcode, mpesa_receipt_number='OWN001')
        resp = auth_client.get(LIST_URL)
        assert resp.status_code == 200
        receipts = [t['mpesa_receipt_number'] for t in resp.data['results']]
        assert 'OWN001' in receipts

    def test_excludes_other_company_transactions(self, auth_client, shortcode, other_shortcode):
        TransactionFactory(shortcode=shortcode, mpesa_receipt_number='MINE')
        TransactionFactory(shortcode=other_shortcode, mpesa_receipt_number='THEIRS')
        resp = auth_client.get(LIST_URL)
        receipts = [t['mpesa_receipt_number'] for t in resp.data['results']]
        assert 'MINE' in receipts
        assert 'THEIRS' not in receipts

    def test_filter_by_status(self, auth_client, shortcode):
        TransactionFactory(shortcode=shortcode, status='completed', mpesa_receipt_number='C001')
        TransactionFactory(shortcode=shortcode, status='pending', mpesa_receipt_number=None, checkout_request_id='STK001')
        resp = auth_client.get(LIST_URL, {'status': 'completed'})
        results = resp.data['results']
        assert all(t['status'] == 'completed' for t in results)

    def test_filter_by_type(self, auth_client, shortcode):
        TransactionFactory(shortcode=shortcode, transaction_type='c2b_paybill', mpesa_receipt_number='P001')
        TransactionFactory(shortcode=shortcode, transaction_type='stk_push', mpesa_receipt_number='S001')
        resp = auth_client.get(LIST_URL, {'type': 'c2b_paybill'})
        results = resp.data['results']
        assert all(t['transaction_type'] == 'c2b_paybill' for t in results)

    def test_filter_by_shortcode_uid(self, auth_client, db, auth_client_extra=None):
        sc1 = ShortcodeFactory(client=auth_client._user)
        sc2 = ShortcodeFactory(client=auth_client._user)
        TransactionFactory(shortcode=sc1, mpesa_receipt_number='SC1-001')
        TransactionFactory(shortcode=sc2, mpesa_receipt_number='SC2-001')
        resp = auth_client.get(LIST_URL, {'shortcode': str(sc1.uid)})
        receipts = [t['mpesa_receipt_number'] for t in resp.data['results']]
        assert 'SC1-001' in receipts
        assert 'SC2-001' not in receipts

    def test_response_does_not_include_raw_payload(self, auth_client, shortcode):
        TransactionFactory(shortcode=shortcode)
        resp = auth_client.get(LIST_URL)
        assert 'raw_payload' not in resp.data['results'][0]


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

class TestTransactionDetail:
    def test_retrieve_own_transaction(self, auth_client, shortcode):
        txn = TransactionFactory(shortcode=shortcode)
        resp = auth_client.get(reverse('transaction-detail', kwargs={'uid': txn.uid}))
        assert resp.status_code == 200
        assert resp.data['mpesa_receipt_number'] == txn.mpesa_receipt_number

    def test_cannot_retrieve_other_company_transaction(self, auth_client, other_shortcode):
        txn = TransactionFactory(shortcode=other_shortcode)
        resp = auth_client.get(reverse('transaction-detail', kwargs={'uid': txn.uid}))
        assert resp.status_code == 404

    def test_detail_is_read_only(self, auth_client, shortcode):
        txn = TransactionFactory(shortcode=shortcode)
        resp = auth_client.patch(
            reverse('transaction-detail', kwargs={'uid': txn.uid}),
            {'amount': '999.00'},
            format='json',
        )
        assert resp.status_code == 405


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class TestTransactionSummary:
    def test_total_received_sums_completed(self, auth_client, shortcode):
        TransactionFactory(shortcode=shortcode, status='completed', amount=Decimal('100.00'))
        TransactionFactory(shortcode=shortcode, status='completed', amount=Decimal('200.00'))
        TransactionFactory(shortcode=shortcode, status='failed', amount=Decimal('50.00'))
        resp = auth_client.get(SUMMARY_URL)
        assert resp.status_code == 200
        assert Decimal(str(resp.data['total_received'])) == Decimal('300.00')

    def test_counts_by_status(self, auth_client, shortcode):
        TransactionFactory(shortcode=shortcode, status='completed')
        TransactionFactory(shortcode=shortcode, status='completed')
        TransactionFactory(shortcode=shortcode, status='pending', mpesa_receipt_number=None, checkout_request_id='STK-A')
        TransactionFactory(shortcode=shortcode, status='failed', mpesa_receipt_number=None, checkout_request_id='STK-B')
        resp = auth_client.get(SUMMARY_URL)
        assert resp.data['completed_count'] == 2
        assert resp.data['pending_count'] == 1
        assert resp.data['failed_count'] == 1
        assert resp.data['total_count'] == 4

    def test_by_type_breakdown(self, auth_client, shortcode):
        TransactionFactory(shortcode=shortcode, transaction_type='c2b_paybill', amount=Decimal('100.00'))
        TransactionFactory(shortcode=shortcode, transaction_type='stk_push', amount=Decimal('200.00'), mpesa_receipt_number='STK001')
        resp = auth_client.get(SUMMARY_URL)
        assert resp.data['by_type']['c2b_paybill']['count'] == 1
        assert resp.data['by_type']['stk_push']['count'] == 1

    def test_excludes_other_company_from_summary(self, auth_client, shortcode, other_shortcode):
        TransactionFactory(shortcode=shortcode, amount=Decimal('100.00'))
        TransactionFactory(shortcode=other_shortcode, amount=Decimal('999.00'))
        resp = auth_client.get(SUMMARY_URL)
        assert Decimal(str(resp.data['total_received'])) == Decimal('100.00')

    def test_empty_summary_returns_zeros(self, auth_client, db):
        resp = auth_client.get(SUMMARY_URL)
        assert resp.status_code == 200
        assert resp.data['total_count'] == 0
        assert Decimal(str(resp.data['total_received'])) == Decimal('0')
