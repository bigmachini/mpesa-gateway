# M-Pesa Payment Gateway

Multi-tenant M-Pesa payment gateway built on Django + Daraja API.

---

## Running with Docker (recommended)

### Prerequisites
- Docker Desktop (or Docker Engine + Compose plugin)

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in at minimum:
```
SECRET_KEY=any-random-string-for-local-dev
DATABASE_URL=postgres://user:password@your-db-host:5432/mpesa_gateway
REDIS_URL=redis://your-redis-host:6379/0
RABBITMQ_URL=amqp://user:password@your-rabbitmq-host:5672/
```

> PostgreSQL, Redis, and RabbitMQ are hosted externally — point the URLs at your external instances.
> - **Redis** is used only for caching (Daraja OAuth token storage)
> - **RabbitMQ** is the Celery message broker (webhook delivery, task queues)

### 2. Start all services

```bash
docker compose up --build
```

This starts:
| Service | Port | Description |
|---------|------|-------------|
| `web` | 8000 | Django dev server (auto-reloads on code changes) |
| `celery` | — | Celery worker (default + webhooks queues) |

Migrations run automatically on `web` startup.

### 3. Create a superuser

```bash
docker compose exec web python manage.py createsuperuser --settings=config.settings.development
```

### 4. Access

- API: http://localhost:8000/api/v1/
- Admin: http://localhost:8000/admin/

### Useful Docker commands

```bash
# Run migrations manually
docker compose exec web python manage.py migrate --settings=config.settings.development

# Open a Django shell
docker compose exec web python manage.py shell --settings=config.settings.development

# Run tests
docker compose exec web python manage.py test --settings=config.settings.development

# Tail logs for a specific service
docker compose logs -f web
docker compose logs -f celery

# Stop everything
docker compose down

# Stop and wipe the database volume
docker compose down -v
```

---

## Running manually (PyCharm / local debugging)

### Prerequisites
- Python 3.12+
- PostgreSQL 16 running locally
- Redis 7 running locally

### 1. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
.venv\Scripts\activate         # Windows
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` for local services:
```
SECRET_KEY=any-random-string-for-local-dev
DATABASE_URL=postgres://your_user:your_password@localhost:5432/mpesa_gateway
REDIS_URL=redis://localhost:6379/0
```

Create the database:
```bash
createdb mpesa_gateway
```

### 4. Run migrations

```bash
python manage.py migrate --settings=config.settings.development
```

### 5. Create a superuser

```bash
python manage.py createsuperuser --settings=config.settings.development
```

### 6. Start the development server

```bash
python manage.py runserver --settings=config.settings.development
```

### 7. Start the Celery worker (separate terminal)

```bash
celery -A config worker -Q default,webhooks --loglevel=info
```

---

## PyCharm run configuration

To use the PyCharm debugger with breakpoints:

1. **Django server:** Go to **Run > Edit Configurations > + > Django Server**
   - Set **Environment variables:** `DJANGO_SETTINGS_MODULE=config.settings.development`
   - Set the project root and manage.py path
   - You can now set breakpoints and use the debugger normally

2. **Celery worker:** Go to **Run > Edit Configurations > + > Python**
   - **Module:** `celery`
   - **Parameters:** `-A config worker -Q default,webhooks --loglevel=info`
   - **Environment variables:** `DJANGO_SETTINGS_MODULE=config.settings.development`

> When debugging with PyCharm, point `DATABASE_URL` and `REDIS_URL` in `.env` at your external PostgreSQL and Redis instances directly.

---

## Running tests

```bash
# All tests
pytest

# Single app
pytest apps/accounts/

# Single test
pytest apps/accounts/tests/test_views.py::RegisterViewTest::test_registration_success
```
