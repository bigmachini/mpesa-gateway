# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **multi-tenant M-Pesa payment gateway** built on Django. It wraps Safaricom's Daraja API so businesses can receive M-Pesa payments (C2B Paybill, C2B Lipa na M-Pesa, STK Push) without doing their own Safaricom integration. The full specification is in `MPESA_GATEWAY_SPEC.md`.

## Tech Stack

- Django 4.2+ with Django REST Framework
- PostgreSQL (primary DB)
- Redis (cache + Celery broker)
- Celery (webhook retries, token refresh, STK callbacks)
- `djangorestframework-simplejwt` for auth
- `django-encrypted-model-fields` for credential encryption at rest
- `django-environ` for env config

## Project Layout

```
mpesa_gateway/
├── config/
│   ├── settings/base.py, development.py, production.py
│   ├── urls.py
│   └── celery.py
├── apps/
│   ├── accounts/      # Client registration, JWT auth, profile
│   ├── shortcodes/    # Paybill/Till management per client
│   ├── daraja/        # All Safaricom Daraja API calls (auth, c2b, stk, callbacks)
│   ├── transactions/  # Immutable incoming transaction ledger
│   ├── wallets/       # Shared Till internal wallet + ledger entries
│   ├── webhooks/      # Webhook registration & Celery-driven delivery
│   └── withdrawals/   # Withdrawal request management (Shared Till only)
```

## Common Commands

```bash
# Run development server
python manage.py runserver --settings=config.settings.development

# Run migrations
python manage.py migrate --settings=config.settings.development

# Create migrations
python manage.py makemigrations --settings=config.settings.development

# Run all tests
python manage.py test --settings=config.settings.development

# Run tests for a specific app
python manage.py test apps.daraja --settings=config.settings.development

# Run a single test
python manage.py test apps.daraja.tests.test_callbacks.C2BConfirmViewTest.test_duplicate_receipt --settings=config.settings.development

# Start Celery worker (two queues)
celery -A config worker -Q default,webhooks --loglevel=info

# Start Celery beat (for scheduled token refreshes if needed)
celery -A config beat --loglevel=info
```

## Key Architecture Decisions

### Two Client Tiers
- **BYOC (Bring Your Own Credentials):** Client provides their own Daraja consumer key/secret/passkey. Each shortcode uses its own OAuth token.
- **Shared Till:** Client uses the platform's shortcode. Platform credentials handle all API calls. Incoming payments are routed by `account_reference` or pre-assigned identifier to the correct client wallet.

### Callback URL Routing via `uid`
The `Shortcode.uid` (UUID) is the only identifier in public-facing callback URLs — never the database PK. Pattern:
```
/api/v1/mpesa/c2b/<uid>/confirm/
/api/v1/mpesa/c2b/<uid>/validate/
/api/v1/mpesa/stk/<uid>/callback/
```
These views are **unauthenticated** (Safaricom sends no auth headers) but must be IP-restricted to Safaricom's known IP ranges.

### Daraja Token Caching
Tokens are cached in Redis with key `daraja:token:<shortcode_uid>`. TTL = `expires_in - 60s`. Never call the Daraja OAuth endpoint per-request — always check Redis first. See `apps/daraja/auth.py`.

### Wallet Integrity (Shared Till)
`Wallet.balance` is never updated directly. All mutations go through `WalletLedgerEntry` records. The balance field is kept in sync but `WalletLedgerEntry` is the source of truth. Withdrawal requests reserve funds (soft-lock) on creation; balance is only debited on `completed`.

### Idempotency
`mpesa_receipt_number` is unique on `Transaction`. If a C2B confirm callback arrives with a duplicate receipt number, return success immediately without creating a new record.

### Celery Queues
Two queues: `default` (general tasks) and `webhooks` (webhook delivery). This prevents webhook retry storms from blocking other work. Webhook retry backoff: 30s → 60s → 5m → 15m → 1h+.

## Admin UI

All admin classes use **Django Unfold** (`django-unfold`). The pattern for every app:

```python
from django.contrib import admin
from unfold.admin import ModelAdmin

@admin.register(MyModel)
class MyModelAdmin(ModelAdmin):
    ...
```

For the `Client` model (extends `AbstractUser`), use multiple inheritance — `ModelAdmin` first:
```python
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from unfold.admin import ModelAdmin

class ClientAdmin(ModelAdmin, BaseUserAdmin):
    ...
```

`unfold`, `unfold.contrib.filters`, and `unfold.contrib.forms` must appear **before** `django.contrib.admin` in `INSTALLED_APPS`. There is no `unfold.contrib.auth` in this version.

## Critical Implementation Rules

- **Credential encryption:** All Daraja credential fields (`consumer_key`, `consumer_secret`, `passkey`, `initiator_name`) on `Shortcode` must use `django-encrypted-model-fields`. Never store as plain text.
- **Money fields:** Always `DecimalField`. Never `FloatField`.
- **Transactions are append-only.** No update or delete endpoints for `Transaction`.
- **`raw_payload`** on `Transaction` stores the exact JSON from Safaricom, unmodified.
- **Shared Till callbacks:** Use `account_reference` to map to the correct client. The `uid` in the callback URL points to the platform shortcode, not an individual client.
- **Phase 2 stubs only:** B2C payouts, bank transfers, webhook HMAC signing, and client API keys are out of scope for now — add stub functions/placeholders but do not implement.

## Environment Variables

Copy `.env.example` and fill in:
```
SECRET_KEY, DEBUG, ALLOWED_HOSTS, DATABASE_URL, REDIS_URL,
DARAJA_CONSUMER_KEY, DARAJA_CONSUMER_SECRET, DARAJA_PASSKEY,
DARAJA_SHORTCODE, DARAJA_ENV (sandbox|production), PLATFORM_BASE_URL
```

## Testing Notes

- Write tests for all callback views using mocked Safaricom payloads. Safaricom sandbox and production payloads differ slightly in field names — document discrepancies in test docstrings.
- Use Django's `TestClient` for callback view tests; mock outbound Daraja API calls with `unittest.mock`.
- Do not squash migrations during the development phase.
