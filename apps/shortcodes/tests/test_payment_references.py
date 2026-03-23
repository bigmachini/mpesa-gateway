"""
Tests for the PaymentReference API endpoint.

POST /api/v1/shortcodes/<uid>/payment-references/
  — Authenticated clients register an expected payment (reference + amount + expiry)
    before directing their customer to pay via Safaricom.

GET  /api/v1/shortcodes/<uid>/payment-references/
  — Lists all references registered against the shortcode.

Only Paybill shortcodes support this endpoint. The shortcode must belong to
the authenticated client.
"""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.tests.factories import ClientFactory
from apps.shortcodes.models import PaymentReference
from apps.shortcodes.tests.factories import PaymentReferenceFactory, ShortcodeFactory


def _future(hours=1):
    return (timezone.now() + timedelta(hours=hours)).isoformat()


@pytest.fixture
def auth_client(db):
    user = ClientFactory(is_active=True)
    client = APIClient()
    client.force_authenticate(user=user)
    client._user = user
    return client


@pytest.fixture
def paybill_shortcode(db, auth_client):
    return ShortcodeFactory(
        client=auth_client._user,
        shortcode_type='paybill',
        tier='byoc',
        enable_c2b_validation=True,
        validation_mode='pre_register',
    )


@pytest.fixture
def other_shortcode(db):
    """A paybill shortcode belonging to a different client."""
    return ShortcodeFactory(shortcode_type='paybill', tier='byoc')


def _url(uid):
    return reverse('payment-reference-list', kwargs={'uid': uid})


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestPaymentReferenceAuth:
    def test_unauthenticated_returns_401(self, db, paybill_shortcode):
        resp = APIClient().post(
            _url(paybill_shortcode.uid),
            {'reference': 'INV001', 'amount': '100.00', 'expires_at': _future()},
            format='json',
        )
        assert resp.status_code == 401

    def test_cannot_access_other_clients_shortcode(self, auth_client, other_shortcode):
        resp = auth_client.get(_url(other_shortcode.uid))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Create (POST)
# ---------------------------------------------------------------------------

class TestCreatePaymentReference:
    def test_create_valid_reference(self, auth_client, paybill_shortcode):
        resp = auth_client.post(
            _url(paybill_shortcode.uid),
            {'reference': 'INV001', 'amount': '250.00', 'expires_at': _future()},
            format='json',
        )
        assert resp.status_code == 201
        assert resp.data['reference'] == 'INV001'
        assert resp.data['amount'] == '250.00'
        assert resp.data['is_used'] is False

    def test_reference_is_saved_to_db(self, auth_client, paybill_shortcode):
        auth_client.post(
            _url(paybill_shortcode.uid),
            {'reference': 'INV-DB-001', 'amount': '99.00', 'expires_at': _future()},
            format='json',
        )
        assert PaymentReference.objects.filter(
            shortcode=paybill_shortcode, reference='INV-DB-001'
        ).exists()

    def test_shortcode_is_set_from_url_not_body(self, auth_client, paybill_shortcode):
        resp = auth_client.post(
            _url(paybill_shortcode.uid),
            {'reference': 'INV002', 'amount': '50.00', 'expires_at': _future()},
            format='json',
        )
        assert resp.status_code == 201
        ref = PaymentReference.objects.get(reference='INV002')
        assert ref.shortcode == paybill_shortcode

    def test_duplicate_reference_for_same_shortcode_rejected(self, auth_client, paybill_shortcode):
        PaymentReferenceFactory(shortcode=paybill_shortcode, reference='DUPE')
        resp = auth_client.post(
            _url(paybill_shortcode.uid),
            {'reference': 'DUPE', 'amount': '100.00', 'expires_at': _future()},
            format='json',
        )
        assert resp.status_code == 400

    def test_same_reference_allowed_on_different_shortcodes(self, auth_client, db):
        sc1 = ShortcodeFactory(client=auth_client._user, shortcode_type='paybill', tier='byoc',
                                enable_c2b_validation=True, validation_mode='pre_register')
        sc2 = ShortcodeFactory(client=auth_client._user, shortcode_type='paybill', tier='byoc',
                                enable_c2b_validation=True, validation_mode='pre_register')
        for sc in (sc1, sc2):
            resp = auth_client.post(
                _url(sc.uid),
                {'reference': 'SHARED-REF', 'amount': '100.00', 'expires_at': _future()},
                format='json',
            )
            assert resp.status_code == 201

    def test_past_expires_at_rejected(self, auth_client, paybill_shortcode):
        past = (timezone.now() - timedelta(minutes=1)).isoformat()
        resp = auth_client.post(
            _url(paybill_shortcode.uid),
            {'reference': 'EXP001', 'amount': '100.00', 'expires_at': past},
            format='json',
        )
        assert resp.status_code == 400

    def test_missing_required_fields_rejected(self, auth_client, paybill_shortcode):
        resp = auth_client.post(_url(paybill_shortcode.uid), {}, format='json')
        assert resp.status_code == 400
        assert 'reference' in resp.data
        assert 'amount' in resp.data

    def test_till_shortcode_returns_404(self, auth_client, db):
        till = ShortcodeFactory(client=auth_client._user, shortcode_type='till', tier='byoc')
        resp = auth_client.post(
            _url(till.uid),
            {'reference': 'INV001', 'amount': '100.00', 'expires_at': _future()},
            format='json',
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# List (GET)
# ---------------------------------------------------------------------------

class TestListPaymentReferences:
    def _results(self, resp):
        """Unwrap paginated or plain list response."""
        if isinstance(resp.data, dict) and 'results' in resp.data:
            return resp.data['results']
        return resp.data

    def test_list_returns_own_references(self, auth_client, paybill_shortcode):
        PaymentReferenceFactory(shortcode=paybill_shortcode, reference='A')
        PaymentReferenceFactory(shortcode=paybill_shortcode, reference='B')
        resp = auth_client.get(_url(paybill_shortcode.uid))
        assert resp.status_code == 200
        refs = [r['reference'] for r in self._results(resp)]
        assert 'A' in refs
        assert 'B' in refs

    def test_list_does_not_include_other_shortcodes_references(self, auth_client, paybill_shortcode, other_shortcode):
        PaymentReferenceFactory(shortcode=paybill_shortcode, reference='MINE')
        PaymentReferenceFactory(shortcode=other_shortcode, reference='THEIRS')
        resp = auth_client.get(_url(paybill_shortcode.uid))
        refs = [r['reference'] for r in self._results(resp)]
        assert 'MINE' in refs
        assert 'THEIRS' not in refs

    def test_is_used_flag_reflected_in_list(self, auth_client, paybill_shortcode):
        PaymentReferenceFactory(shortcode=paybill_shortcode, reference='USED', is_used=True)
        resp = auth_client.get(_url(paybill_shortcode.uid))
        item = next(r for r in self._results(resp) if r['reference'] == 'USED')
        assert item['is_used'] is True
