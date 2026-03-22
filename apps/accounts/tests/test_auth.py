import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Client
from .factories import ClientFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def active_client(db):
    return ClientFactory(is_active=True)


@pytest.fixture
def inactive_client(db):
    return ClientFactory(is_active=False)


REGISTER_URL = reverse("auth-register")
LOGIN_URL = reverse("auth-login")
REFRESH_URL = reverse("auth-token-refresh")
PROFILE_URL = reverse("auth-profile")

VALID_REGISTRATION_PAYLOAD = {
    "email": "newbusiness@example.com",
    "username": "newbusiness",
    "password": "StrongPass123!",
    "business_name": "New Business Ltd",
    "phone_number": "+254712345678",
}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegistration:
    def test_registration_creates_inactive_client(self, api_client, db):
        """Self-registered clients must be inactive pending admin approval."""
        response = api_client.post(REGISTER_URL, VALID_REGISTRATION_PAYLOAD, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        client = Client.objects.get(email=VALID_REGISTRATION_PAYLOAD["email"])
        assert client.is_active is False

    def test_registration_returns_no_tokens(self, api_client, db):
        """Registration response must not include access/refresh tokens."""
        response = api_client.post(REGISTER_URL, VALID_REGISTRATION_PAYLOAD, format="json")

        assert "access" not in response.data
        assert "refresh" not in response.data

    def test_registration_duplicate_email_rejected(self, api_client, active_client):
        payload = {**VALID_REGISTRATION_PAYLOAD, "email": active_client.email}
        response = api_client.post(REGISTER_URL, payload, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_registration_missing_required_fields_rejected(self, api_client, db):
        response = api_client.post(REGISTER_URL, {"email": "x@x.com"}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_inactive_client_cannot_login(self, api_client, inactive_client):
        """Core regression: inactive clients must be rejected at login."""
        response = api_client.post(
            LOGIN_URL,
            {"email": inactive_client.email, "password": "testpass123"},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert "access" not in response.data

    def test_active_client_can_login(self, api_client, active_client):
        response = api_client.post(
            LOGIN_URL,
            {"email": active_client.email, "password": "testpass123"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data

    def test_login_response_includes_tier_and_business_name(self, api_client, active_client):
        response = api_client.post(
            LOGIN_URL,
            {"email": active_client.email, "password": "testpass123"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["tier"] == active_client.tier
        assert response.data["business_name"] == active_client.business_name

    def test_wrong_password_rejected(self, api_client, active_client):
        response = api_client.post(
            LOGIN_URL,
            {"email": active_client.email, "password": "wrongpassword"},
            format="json",
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_superuser_created_programmatically_is_active(self, db):
        """Regression: superusers must have is_active=True so admin login works."""
        superuser = Client.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="adminpass123",
        )

        assert superuser.is_active is True
        assert superuser.is_superuser is True


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------

class TestTokenRefresh:
    def test_valid_refresh_token_returns_new_access_token(self, api_client, active_client):
        login = api_client.post(
            LOGIN_URL,
            {"email": active_client.email, "password": "testpass123"},
            format="json",
        )
        refresh_token = login.data["refresh"]

        response = api_client.post(REFRESH_URL, {"refresh": refresh_token}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data

    def test_invalid_refresh_token_rejected(self, api_client, db):
        response = api_client.post(REFRESH_URL, {"refresh": "not-a-real-token"}, format="json")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class TestProfile:
    def test_unauthenticated_request_rejected(self, api_client, db):
        response = api_client.get(PROFILE_URL)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_authenticated_client_can_retrieve_profile(self, api_client, active_client):
        api_client.force_authenticate(user=active_client)
        response = api_client.get(PROFILE_URL)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["email"] == active_client.email
        assert response.data["business_name"] == active_client.business_name

    def test_client_can_update_business_name(self, api_client, active_client):
        api_client.force_authenticate(user=active_client)
        response = api_client.patch(
            PROFILE_URL,
            {"business_name": "Updated Name Ltd"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        active_client.refresh_from_db()
        assert active_client.business_name == "Updated Name Ltd"

    def test_client_cannot_change_own_tier(self, api_client, active_client):
        """Tier is read-only — clients cannot self-promote to shared tier."""
        api_client.force_authenticate(user=active_client)
        response = api_client.patch(
            PROFILE_URL,
            {"tier": "shared"},
            format="json",
        )

        active_client.refresh_from_db()
        assert active_client.tier == "byoc"

    def test_client_cannot_change_own_email(self, api_client, active_client):
        """Email is read-only on the profile endpoint."""
        original_email = active_client.email
        api_client.force_authenticate(user=active_client)
        api_client.patch(PROFILE_URL, {"email": "newemail@example.com"}, format="json")

        active_client.refresh_from_db()
        assert active_client.email == original_email
