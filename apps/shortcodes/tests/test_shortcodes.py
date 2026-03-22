import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.shortcodes.models import Shortcode
from .factories import ShortcodeFactory
from apps.accounts.tests.factories import ClientFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def client_user(db):
    return ClientFactory(is_active=True)


@pytest.fixture
def other_client(db):
    return ClientFactory(is_active=True)


@pytest.fixture
def shortcode(db, client_user):
    return ShortcodeFactory(client=client_user)


LIST_URL = reverse('shortcode-list')

BYOC_PAYBILL_PAYLOAD = {
    'shortcode_type': 'paybill',
    'tier': 'byoc',
    'shortcode_number': '600999',
    'display_name': 'Main Paybill',
    'consumer_key': 'ck-test',
    'consumer_secret': 'cs-test',
    'passkey': 'pk-test',
}

SHARED_PAYBILL_PAYLOAD = {
    'shortcode_type': 'paybill',
    'tier': 'shared',
    # display_name intentionally omitted — auto-set from client.business_name
    # shortcode_number intentionally omitted — auto-set from DARAJA_SHORTCODE
}


# ---------------------------------------------------------------------------
# List & Create
# ---------------------------------------------------------------------------

class TestShortcodeListCreate:
    def test_unauthenticated_request_rejected(self, api_client, db):
        response = api_client.get(LIST_URL)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_client_only_sees_own_shortcodes(self, api_client, client_user, other_client, db):
        ShortcodeFactory(client=client_user)
        ShortcodeFactory(client=other_client)

        api_client.force_authenticate(user=client_user)
        response = api_client.get(LIST_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.data['count'] == 1

    def test_create_byoc_paybill_shortcode(self, api_client, client_user, db):
        api_client.force_authenticate(user=client_user)
        response = api_client.post(LIST_URL, BYOC_PAYBILL_PAYLOAD, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert Shortcode.objects.filter(client=client_user).count() == 1

    def test_create_assigns_shortcode_to_authenticated_client(self, api_client, client_user, db):
        api_client.force_authenticate(user=client_user)
        api_client.post(LIST_URL, BYOC_PAYBILL_PAYLOAD, format='json')

        shortcode = Shortcode.objects.get(shortcode_number='600999')
        assert shortcode.client == client_user

    def test_create_shared_paybill_no_credentials_required(self, api_client, client_user, db):
        api_client.force_authenticate(user=client_user)
        response = api_client.post(LIST_URL, SHARED_PAYBILL_PAYLOAD, format='json')

        assert response.status_code == status.HTTP_201_CREATED

    def test_shared_till_type_rejected(self, api_client, client_user, db):
        """Shared tier is not available for Lipa na M-Pesa (till) — no account number field."""
        payload = {'shortcode_type': 'till', 'tier': 'shared', 'display_name': 'Bad Till'}
        api_client.force_authenticate(user=client_user)
        response = api_client.post(LIST_URL, payload, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'tier' in response.data

    def test_shared_paybill_gets_account_code(self, api_client, client_user, db):
        """Shared Till shortcodes must have a 6-digit account code auto-assigned."""
        api_client.force_authenticate(user=client_user)
        response = api_client.post(LIST_URL, SHARED_PAYBILL_PAYLOAD, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        shortcode = Shortcode.objects.get(client=client_user, tier='shared')
        assert shortcode.account_code is not None
        assert len(shortcode.account_code) == 6
        assert shortcode.account_code.isdigit()

    def test_shared_paybill_display_name_auto_set_from_config(self, api_client, client_user, db, settings):
        """display_name is auto-populated from DARAJA_DISPLAY_NAME config; client cannot override it."""
        settings.DARAJA_DISPLAY_NAME = 'Platform Paybill'
        api_client.force_authenticate(user=client_user)
        response = api_client.post(LIST_URL, SHARED_PAYBILL_PAYLOAD, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        shortcode = Shortcode.objects.get(client=client_user, tier='shared')
        assert shortcode.display_name == 'Platform Paybill'

    def test_shared_paybill_account_codes_are_unique(self, api_client, client_user, other_client, db):
        api_client.force_authenticate(user=client_user)
        api_client.post(LIST_URL, SHARED_PAYBILL_PAYLOAD, format='json')

        api_client.force_authenticate(user=other_client)
        api_client.post(LIST_URL, SHARED_PAYBILL_PAYLOAD, format='json')

        codes = list(Shortcode.objects.filter(tier='shared').values_list('account_code', flat=True))
        assert len(codes) == len(set(codes))

    def test_shared_paybill_shortcode_number_auto_set(self, api_client, client_user, db, settings):
        """Platform Paybill number is auto-assigned; client cannot override it."""
        settings.DARAJA_SHORTCODE = '400200'
        api_client.force_authenticate(user=client_user)
        response = api_client.post(LIST_URL, SHARED_PAYBILL_PAYLOAD, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        shortcode = Shortcode.objects.get(client=client_user, tier='shared')
        assert shortcode.shortcode_number == '400200'

    def test_shared_paybill_preferred_code_accepted_when_available(self, api_client, client_user, db):
        payload = {**SHARED_PAYBILL_PAYLOAD, 'account_code': '123456'}
        api_client.force_authenticate(user=client_user)
        response = api_client.post(LIST_URL, payload, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        shortcode = Shortcode.objects.get(client=client_user, tier='shared')
        assert shortcode.account_code == '123456'

    def test_shared_paybill_taken_code_returns_suggestions(self, api_client, client_user, other_client, db):
        """If preferred code is taken, response must include available suggestions."""
        from apps.shortcodes.tests.factories import ShortcodeFactory
        ShortcodeFactory(client=other_client, tier='shared', account_code='123456', shortcode_number='400200')

        payload = {**SHARED_PAYBILL_PAYLOAD, 'account_code': '123456'}
        api_client.force_authenticate(user=client_user)
        response = api_client.post(LIST_URL, payload, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error_text = str(response.data['account_code'])
        assert '123456' in error_text
        assert '123457' in error_text or '123455' in error_text  # at least one suggestion nearby

    def test_shared_paybill_code_not_changeable_after_creation(self, api_client, client_user, db):
        """account_code must be immutable after assignment."""
        payload = {**SHARED_PAYBILL_PAYLOAD, 'account_code': '111111'}
        api_client.force_authenticate(user=client_user)
        api_client.post(LIST_URL, payload, format='json')

        shortcode = Shortcode.objects.get(client=client_user, tier='shared')
        url = reverse('shortcode-detail', kwargs={'uid': shortcode.uid})
        api_client.patch(url, {'account_code': '999999'}, format='json')

        shortcode.refresh_from_db()
        assert shortcode.account_code == '111111'

    def test_shared_paybill_invalid_code_format_rejected(self, api_client, client_user, db):
        for bad_code in ['12345', '1234567', 'ABCDEF', '12 345']:
            payload = {**SHARED_PAYBILL_PAYLOAD, 'account_code': bad_code}
            api_client.force_authenticate(user=client_user)
            response = api_client.post(LIST_URL, payload, format='json')
            assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Expected rejection for code: {bad_code}"

    def test_byoc_till_shortcode_allowed(self, api_client, client_user, db):
        """BYOC clients can still have Lipa na M-Pesa (till) shortcodes."""
        payload = {
            'shortcode_type': 'till',
            'tier': 'byoc',
            'shortcode_number': '5551234',
            'display_name': 'My Till',
            'consumer_key': 'ck',
            'consumer_secret': 'cs',
        }
        api_client.force_authenticate(user=client_user)
        response = api_client.post(LIST_URL, payload, format='json')

        assert response.status_code == status.HTTP_201_CREATED

    def test_byoc_paybill_without_passkey_rejected(self, api_client, client_user, db):
        payload = {**BYOC_PAYBILL_PAYLOAD}
        del payload['passkey']

        api_client.force_authenticate(user=client_user)
        response = api_client.post(LIST_URL, payload, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'passkey' in response.data

    def test_byoc_without_consumer_key_rejected(self, api_client, client_user, db):
        payload = {**BYOC_PAYBILL_PAYLOAD}
        del payload['consumer_key']

        api_client.force_authenticate(user=client_user)
        response = api_client.post(LIST_URL, payload, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'consumer_key' in response.data

    def test_duplicate_shortcode_number_per_client_rejected(self, api_client, client_user, shortcode, db):
        payload = {**BYOC_PAYBILL_PAYLOAD, 'shortcode_number': shortcode.shortcode_number}
        api_client.force_authenticate(user=client_user)
        response = api_client.post(LIST_URL, payload, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_same_shortcode_number_allowed_for_different_clients(self, api_client, client_user, other_client, db):
        ShortcodeFactory(client=other_client, shortcode_number='600999')

        api_client.force_authenticate(user=client_user)
        response = api_client.post(LIST_URL, BYOC_PAYBILL_PAYLOAD, format='json')

        assert response.status_code == status.HTTP_201_CREATED

    def test_create_response_does_not_expose_credentials(self, api_client, client_user, db):
        """consumer_secret and passkey are write-only — must not appear in response."""
        api_client.force_authenticate(user=client_user)
        response = api_client.post(LIST_URL, BYOC_PAYBILL_PAYLOAD, format='json')

        assert 'consumer_secret' not in response.data
        assert 'passkey' not in response.data


# ---------------------------------------------------------------------------
# Retrieve / Update / Delete
# ---------------------------------------------------------------------------

class TestShortcodeDetail:
    def test_retrieve_own_shortcode(self, api_client, client_user, shortcode):
        api_client.force_authenticate(user=client_user)
        url = reverse('shortcode-detail', kwargs={'uid': shortcode.uid})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert str(response.data['uid']) == str(shortcode.uid)

    def test_cannot_retrieve_other_clients_shortcode(self, api_client, other_client, shortcode):
        api_client.force_authenticate(user=other_client)
        url = reverse('shortcode-detail', kwargs={'uid': shortcode.uid})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_update_display_name(self, api_client, client_user, shortcode):
        api_client.force_authenticate(user=client_user)
        url = reverse('shortcode-detail', kwargs={'uid': shortcode.uid})
        response = api_client.patch(url, {'display_name': 'Updated Name'}, format='json')

        assert response.status_code == status.HTTP_200_OK
        shortcode.refresh_from_db()
        assert shortcode.display_name == 'Updated Name'

    def test_delete_own_shortcode(self, api_client, client_user, shortcode):
        api_client.force_authenticate(user=client_user)
        url = reverse('shortcode-detail', kwargs={'uid': shortcode.uid})
        response = api_client.delete(url)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Shortcode.objects.filter(uid=shortcode.uid).exists()

    def test_cannot_delete_other_clients_shortcode(self, api_client, other_client, shortcode):
        api_client.force_authenticate(user=other_client)
        url = reverse('shortcode-detail', kwargs={'uid': shortcode.uid})
        response = api_client.delete(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert Shortcode.objects.filter(uid=shortcode.uid).exists()


# ---------------------------------------------------------------------------
# Callback URLs
# ---------------------------------------------------------------------------

class TestCallbackURLs:
    def test_callback_urls_contain_uid(self, api_client, client_user, shortcode):
        api_client.force_authenticate(user=client_user)
        url = reverse('shortcode-callback-urls', kwargs={'uid': shortcode.uid})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        for key, value in response.data.items():
            assert str(shortcode.uid) in value

    def test_callback_urls_have_correct_keys(self, api_client, client_user, shortcode):
        api_client.force_authenticate(user=client_user)
        url = reverse('shortcode-callback-urls', kwargs={'uid': shortcode.uid})
        response = api_client.get(url)

        assert set(response.data.keys()) == {'c2b_confirmation', 'c2b_validation', 'stk_callback'}

    def test_cannot_get_callback_urls_for_other_clients_shortcode(self, api_client, other_client, shortcode):
        api_client.force_authenticate(user=other_client)
        url = reverse('shortcode-callback-urls', kwargs={'uid': shortcode.uid})
        response = api_client.get(url)

        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# Webhook URL
# ---------------------------------------------------------------------------

class TestWebhookURL:
    def test_set_webhook_url(self, api_client, client_user, shortcode):
        api_client.force_authenticate(user=client_user)
        url = reverse('shortcode-webhook', kwargs={'uid': shortcode.uid})
        response = api_client.put(url, {'webhook_url': 'https://myapp.com/webhook/'}, format='json')

        assert response.status_code == status.HTTP_200_OK
        shortcode.refresh_from_db()
        assert shortcode.webhook_url == 'https://myapp.com/webhook/'

    def test_clear_webhook_url(self, api_client, client_user, shortcode):
        shortcode.webhook_url = 'https://myapp.com/webhook/'
        shortcode.save()

        api_client.force_authenticate(user=client_user)
        url = reverse('shortcode-webhook', kwargs={'uid': shortcode.uid})
        response = api_client.put(url, {'webhook_url': None}, format='json')

        assert response.status_code == status.HTTP_200_OK
        shortcode.refresh_from_db()
        assert shortcode.webhook_url is None

    def test_invalid_webhook_url_rejected(self, api_client, client_user, shortcode):
        api_client.force_authenticate(user=client_user)
        url = reverse('shortcode-webhook', kwargs={'uid': shortcode.uid})
        response = api_client.put(url, {'webhook_url': 'not-a-url'}, format='json')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_cannot_set_webhook_for_other_clients_shortcode(self, api_client, other_client, shortcode):
        api_client.force_authenticate(user=other_client)
        url = reverse('shortcode-webhook', kwargs={'uid': shortcode.uid})
        response = api_client.put(url, {'webhook_url': 'https://evil.com/hook/'}, format='json')

        assert response.status_code == status.HTTP_404_NOT_FOUND
