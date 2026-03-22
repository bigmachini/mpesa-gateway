# M-Pesa Payment Gateway — Django Build Specification

## Project Overview

Build a multi-tenant M-Pesa payment gateway that sits on top of Safaricom's Daraja API.
The platform allows businesses to receive M-Pesa payments (C2B Paybill, C2B Lipa na M-Pesa,
and STK Push) without any Safaricom integration work on their end. Clients sign up, enter
their details, and start processing transactions immediately.

---

## Tech Stack

- **Backend:** Django 4.2+ with Django REST Framework
- **Database:** PostgreSQL
- **Cache / Queue Broker:** Redis
- **Task Queue:** Celery (for webhook retries, token refresh, STK callbacks)
- **Auth:** JWT via `djangorestframework-simplejwt`
- **HTTP Client:** `requests` or `httpx` for Daraja API calls
- **Environment config:** `django-environ`

---

## Project Structure

```
mpesa_gateway/
├── config/
│   ├── settings/
│   │   ├── base.py
│   │   ├── development.py
│   │   └── production.py
│   ├── urls.py
│   └── celery.py
├── apps/
│   ├── accounts/          # Client registration, auth, profile
│   ├── shortcodes/        # Paybill & Till management per client
│   ├── daraja/            # All Safaricom Daraja API integration logic
│   ├── transactions/      # Incoming transaction recording & ledger
│   ├── wallets/           # Shared Till internal wallet engine
│   ├── webhooks/          # Client webhook registration & delivery
│   └── withdrawals/       # Withdrawal request management (Shared Till)
├── manage.py
├── requirements.txt
└── .env.example
```

---

## App-by-App Specification

---

### 1. `accounts` — Client Management

**Purpose:** Handle client registration, authentication, and profile management.

#### Models

```python
# Client account (one per business)
class Client(AbstractUser):
    business_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField(unique=True)
    tier = models.CharField(
        max_length=20,
        choices=[('byoc', 'Bring Your Own Credentials'), ('shared', 'Shared Till')],
        default='byoc'
    )
    is_active = models.BooleanField(default=False)  # activated after admin approval
    created_at = models.DateTimeField(auto_now_add=True)
```

#### API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| POST | `/api/v1/auth/register/` | Client registration |
| POST | `/api/v1/auth/login/` | Obtain JWT token pair |
| POST | `/api/v1/auth/token/refresh/` | Refresh access token |
| GET/PUT | `/api/v1/auth/profile/` | View and update profile |

---

### 2. `shortcodes` — Paybill & Till Management

**Purpose:** Clients register and manage their Paybill numbers and Till numbers here.
Each shortcode holds the Daraja credentials needed to interact with Safaricom on the
client's behalf (for BYOC clients). Shared Till clients are linked to the platform shortcode.

#### Models

```python
class Shortcode(models.Model):
    SHORTCODE_TYPES = [
        ('paybill', 'Paybill'),
        ('till', 'Lipa na M-Pesa (Buy Goods)'),
    ]
    TIER_TYPES = [
        ('byoc', 'Bring Your Own Credentials'),
        ('shared', 'Shared Till'),
    ]

    client = models.ForeignKey('accounts.Client', on_delete=models.CASCADE, related_name='shortcodes')
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)  # used in callback URLs
    shortcode_type = models.CharField(max_length=20, choices=SHORTCODE_TYPES)
    tier = models.CharField(max_length=20, choices=TIER_TYPES)
    shortcode_number = models.CharField(max_length=20)  # actual Safaricom shortcode
    display_name = models.CharField(max_length=255)     # friendly name e.g. "Main Store Till"

    # Daraja credentials — only populated for BYOC clients
    consumer_key = models.CharField(max_length=255, blank=True)
    consumer_secret = models.CharField(max_length=255, blank=True)
    passkey = models.CharField(max_length=500, blank=True)      # for STK Push
    initiator_name = models.CharField(max_length=255, blank=True)

    # Webhook config
    webhook_url = models.URLField(blank=True, null=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('client', 'shortcode_number')
```

**Notes:**
- For **Shared Till** clients, `shortcode_number` is set to the platform's own shortcode.
  The `uid` is still unique per client so callbacks can be routed correctly.
- Daraja credential fields are **encrypted at rest** using `django-encrypted-model-fields`
  or equivalent.
- The `uid` field drives the auto-generated callback URL pattern.

#### Auto-generated Callback URLs (display only, copy to clipboard)

```
C2B Confirmation : https://<domain>/api/v1/mpesa/c2b/<uid>/confirm/
C2B Validation   : https://<domain>/api/v1/mpesa/c2b/<uid>/validate/
STK Callback     : https://<domain>/api/v1/mpesa/stk/<uid>/callback/
```

These are shown on the shortcode detail page. BYOC clients register them with Safaricom
manually. Shared Till callbacks are pre-registered by the platform.

#### API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET/POST | `/api/v1/shortcodes/` | List and create shortcodes |
| GET/PUT/DELETE | `/api/v1/shortcodes/<uid>/` | Retrieve, update, delete a shortcode |
| GET | `/api/v1/shortcodes/<uid>/callback-urls/` | Get generated callback URLs |
| PUT | `/api/v1/shortcodes/<uid>/webhook/` | Set or update webhook URL |

---

### 3. `daraja` — Safaricom Daraja Integration Layer

**Purpose:** All communication with the Safaricom Daraja API lives here. No other app
should talk to Safaricom directly — everything routes through this app.

#### Sub-modules

```
daraja/
├── auth.py          # OAuth token fetch and cache per shortcode
├── c2b.py           # C2B registration (validation/confirmation URLs)
├── stk.py           # STK Push initiation
├── callbacks.py     # Callback URL views (receives Safaricom postbacks)
└── utils.py         # Shared helpers (timestamp, password generation, etc.)
```

#### Token Management (`auth.py`)

- Each BYOC shortcode has its own consumer key/secret → its own token
- Platform shortcode has one token for all Shared Till clients
- Tokens are cached in Redis with key `daraja:token:<shortcode_uid>`
- Cache TTL is set to the token's `expires_in` minus a 60-second buffer
- Token is auto-refreshed on cache miss before any API call

```python
def get_access_token(shortcode: Shortcode) -> str:
    """
    Returns a valid Daraja access token for the given shortcode.
    Fetches from Redis cache first; calls Daraja OAuth if expired or missing.
    """
```

#### STK Push (`stk.py`)

```python
def initiate_stk_push(shortcode: Shortcode, phone: str, amount: int, account_ref: str, description: str) -> dict:
    """
    Initiates an STK Push (Lipa na M-Pesa Online) request.
    Works for both BYOC and Shared Till clients.
    Returns the raw Daraja response.
    """
```

- For Shared Till: uses platform credentials, `account_ref` must encode the client's `uid`
  so the STK callback can route the transaction to the correct client wallet.
- For BYOC: uses the client's own credentials.

#### C2B Callbacks (`callbacks.py`)

These are the views that Safaricom calls. They are **unauthenticated** (Safaricom does not
send auth headers) but should be rate-limited and IP-restricted to Safaricom's known IP ranges.

```
POST /api/v1/mpesa/c2b/<uid>/validate/    — C2B Validation (optional, respond ACCEPTED)
POST /api/v1/mpesa/c2b/<uid>/confirm/     — C2B Confirmation (record transaction)
POST /api/v1/mpesa/stk/<uid>/callback/    — STK Push result callback
```

**Callback flow:**
1. Receive payload from Safaricom
2. Verify `uid` maps to a known active shortcode
3. Parse and save transaction to `transactions` app
4. For Shared Till: credit the client's wallet
5. Dispatch Celery task to forward payload to client's webhook URL (if set)
6. Return `{"ResultCode": 0, "ResultDesc": "Accepted"}` immediately

#### API Endpoints (client-facing)

| Method | URL | Description |
|--------|-----|-------------|
| POST | `/api/v1/daraja/stk-push/` | Initiate STK Push for a shortcode |
| GET | `/api/v1/daraja/stk-push/<checkout_request_id>/` | Query STK Push status |

---

### 4. `transactions` — Transaction Ledger

**Purpose:** Immutable record of all incoming transactions across all shortcodes and clients.

#### Models

```python
class Transaction(models.Model):
    TRANSACTION_TYPES = [
        ('c2b_paybill', 'C2B Paybill'),
        ('c2b_till', 'C2B Lipa na M-Pesa'),
        ('stk_push', 'STK Push'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'),      # STK Push initiated, awaiting callback
        ('completed', 'Completed'),  # Successfully received
        ('failed', 'Failed'),        # STK Push failed or cancelled
    ]

    shortcode = models.ForeignKey('shortcodes.Shortcode', on_delete=models.PROTECT, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # M-Pesa fields
    mpesa_receipt_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
    checkout_request_id = models.CharField(max_length=100, null=True, blank=True)  # STK Push
    msisdn = models.CharField(max_length=20)          # payer phone number
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    account_reference = models.CharField(max_length=100, blank=True)  # paybill account number
    transaction_desc = models.TextField(blank=True)
    bill_ref_number = models.CharField(max_length=100, blank=True)

    # Raw payload from Safaricom — never modified
    raw_payload = models.JSONField()

    transaction_time = models.DateTimeField()   # Safaricom timestamp
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-transaction_time']
        indexes = [
            models.Index(fields=['shortcode', 'status']),
            models.Index(fields=['mpesa_receipt_number']),
            models.Index(fields=['msisdn']),
        ]
```

**Rules:**
- Transactions are **append-only**. No update or delete endpoints exposed.
- `raw_payload` stores the exact JSON received from Safaricom, unchanged.

#### API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/v1/transactions/` | List all transactions (filtered by shortcode, date, status) |
| GET | `/api/v1/transactions/<id>/` | Retrieve single transaction |
| GET | `/api/v1/transactions/summary/` | Aggregated stats (total received, count, by type) |

---

### 5. `wallets` — Shared Till Wallet Engine

**Purpose:** Internal ledger for Shared Till clients. Tracks balance as a running sum of
credits (incoming transactions) and debits (approved withdrawal payouts).

#### Models

```python
class Wallet(models.Model):
    client = models.OneToOneField('accounts.Client', on_delete=models.PROTECT)
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)

class WalletLedgerEntry(models.Model):
    ENTRY_TYPES = [
        ('credit', 'Credit'),    # incoming transaction
        ('debit', 'Debit'),      # approved withdrawal
    ]
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name='entries')
    entry_type = models.CharField(max_length=10, choices=ENTRY_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)  # snapshot
    reference = models.CharField(max_length=100)   # transaction ID or withdrawal ID
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

**Rules:**
- Wallet balance is never updated directly. All changes go through ledger entries.
- Balance is always derived from `WalletLedgerEntry` records to ensure auditability.
- Only Shared Till clients have a wallet. BYOC clients do not.

#### API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/v1/wallet/` | Get current wallet balance and summary |
| GET | `/api/v1/wallet/ledger/` | Full ledger history with pagination |

---

### 6. `webhooks` — Client Webhook Delivery

**Purpose:** Forward incoming transaction details to a client's registered webhook URL
per shortcode. Handles retry logic via Celery.

#### Models

```python
class WebhookDelivery(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('retrying', 'Retrying'),
        ('exhausted', 'Exhausted'),   # max retries reached
    ]
    shortcode = models.ForeignKey('shortcodes.Shortcode', on_delete=models.PROTECT)
    transaction = models.ForeignKey('transactions.Transaction', on_delete=models.PROTECT)
    target_url = models.URLField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    attempts = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    response_status_code = models.IntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

#### Celery Task: `deliver_webhook`

```python
@app.task(bind=True, max_retries=None)
def deliver_webhook(self, delivery_id: int):
    """
    POSTs the transaction payload to the client's webhook URL.
    On failure, retries with exponential backoff indefinitely until success.

    Backoff schedule (examples):
      Attempt 1 failure → retry in 30s
      Attempt 2 failure → retry in 60s
      Attempt 3 failure → retry in 5m
      Attempt 4 failure → retry in 15m
      Attempt 5+ failure → retry in 1h
    """
```

**Payload structure sent to client webhook:**
```json
{
  "event": "transaction.received",
  "shortcode": "<shortcode_number>",
  "shortcode_uid": "<uid>",
  "transaction_type": "c2b_paybill | c2b_till | stk_push",
  "mpesa_receipt_number": "...",
  "amount": "...",
  "msisdn": "...",
  "account_reference": "...",
  "transaction_time": "...",
  "timestamp": "<iso8601 time we sent this>"
}
```

#### API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/v1/webhooks/deliveries/` | List all webhook delivery attempts |
| POST | `/api/v1/webhooks/deliveries/<id>/retry/` | Manually trigger a retry |

---

### 7. `withdrawals` — Withdrawal Requests (Shared Till)

**Purpose:** Shared Till clients request a payout from their wallet. The request is logged
and flagged for admin action. Actual transfer execution (B2C or bank) is Phase 2.

#### Models

```python
class WithdrawalRequest(models.Model):
    DESTINATION_TYPES = [
        ('phone', 'M-Pesa Phone Number'),
        ('bank', 'Bank Account'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('rejected', 'Rejected'),
    ]

    client = models.ForeignKey('accounts.Client', on_delete=models.PROTECT)
    wallet = models.ForeignKey('wallets.Wallet', on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    destination_type = models.CharField(max_length=10, choices=DESTINATION_TYPES)
    destination_phone = models.CharField(max_length=20, blank=True)   # if phone
    destination_bank_name = models.CharField(max_length=100, blank=True)  # if bank
    destination_account_number = models.CharField(max_length=50, blank=True)  # if bank
    destination_account_name = models.CharField(max_length=100, blank=True)   # if bank
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_note = models.TextField(blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
```

**Rules:**
- A withdrawal request can only be created if `wallet.balance >= amount`.
- On creation, the requested amount is **reserved** (soft-locked) in the wallet —
  balance is not deducted until the request is marked `completed`.
- On `rejected`, the reservation is released back to available balance.
- On `completed`, a `WalletLedgerEntry` debit is created and the reservation is cleared.

#### API Endpoints

| Method | URL | Description |
|--------|-----|-------------|
| GET/POST | `/api/v1/withdrawals/` | List and create withdrawal requests |
| GET | `/api/v1/withdrawals/<id>/` | Retrieve single request |

---

## Admin Panel

Use Django's built-in admin (`django.contrib.admin`) extended with custom actions.

### What Platform Admins Can Do

- **Accounts:** View all clients, activate/deactivate accounts, change tier
- **Shortcodes:** View all shortcodes across all clients, activate/deactivate
- **Transactions:** View all transactions, filter by client/shortcode/date/status, export CSV
- **Wallets:** View all wallet balances and ledger entries
- **Withdrawals:** Review pending requests, approve or reject with a note, mark as completed
- **Webhook Deliveries:** View delivery logs, manually retry failed deliveries
- **Platform Shortcode:** Manage the platform's own Daraja credentials (used for Shared Till)

---

## Environment Variables (`.env.example`)

```env
# Django
SECRET_KEY=
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgres://user:password@localhost:5432/mpesa_gateway

# Redis
REDIS_URL=redis://localhost:6379/0

# Daraja — Platform credentials (used for Shared Till)
DARAJA_CONSUMER_KEY=
DARAJA_CONSUMER_SECRET=
DARAJA_PASSKEY=
DARAJA_SHORTCODE=
DARAJA_ENV=sandbox   # sandbox | production

# Platform
PLATFORM_BASE_URL=https://yourdomain.com
```

---

## Key Implementation Notes for Claude Code

1. **Credential encryption:** Use `django-encrypted-model-fields` for all Daraja credential
   fields on the `Shortcode` model. Never store them as plain text.

2. **Callback URL routing:** The `uid` field on `Shortcode` is the only identifier used in
   callback URLs. Never expose internal database IDs in public-facing URLs.

3. **Safaricom IP allowlisting:** The C2B and STK callback views should only accept requests
   from Safaricom's known IP ranges. Implement this as a Django middleware or decorator.

4. **Idempotency:** The `confirm` callback from Safaricom can sometimes be delivered more
   than once. Use `mpesa_receipt_number` as a unique key and handle duplicates gracefully
   (return success, do not create duplicate transaction).

5. **Token caching:** Never call the Daraja OAuth endpoint on every request. Always check
   Redis first. Use a per-shortcode cache key.

6. **Celery:** Configure two queues — `default` for general tasks and `webhooks` for
   webhook delivery tasks so webhook retries do not block other work.

7. **Decimal precision:** Always use `DecimalField` for money. Never use `FloatField`.

8. **Shared Till routing:** When a C2B payment comes in on the platform shortcode, use the
   `account_reference` (paybill) or a pre-assigned identifier (till) to map the transaction
   to the correct Shared Till client.

9. **Testing:** Write tests for all callback views using mocked Safaricom payloads.
   Safaricom's sandbox payload structures differ slightly from production — document this.

10. **Migrations:** Keep migrations clean. Do not squash during development phase.

---

## Phase 2 Scope (Not to be built now — stubs only)

- **B2C payout execution** for Shared Till withdrawal requests (phone)
- **Bank transfer integration** for Shared Till withdrawal requests (bank)
- **Webhook payload signing** (HMAC secret per shortcode)
- **Client API keys** for programmatic access to the REST API
- **Transaction exports** (CSV/PDF) from client dashboard
