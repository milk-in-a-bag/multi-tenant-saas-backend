# Quickstart Guide

Get the multi-tenant SaaS backend running locally in about 10 minutes.

---

## Prerequisites

- **Python 3.11+** — [python.org/downloads](https://www.python.org/downloads/)
- **PostgreSQL 14+** — [postgresql.org/download](https://www.postgresql.org/download/)
- **Git**

Verify your versions:

```bash
python --version   # Python 3.11.x or higher
psql --version     # psql (PostgreSQL) 14.x or higher
```

---

## 1. Clone and Set Up

```bash
git clone <your-repo-url>
cd <repo-directory>
```

Create and activate a virtual environment:

```bash
# Create the virtualenv
python -m venv venv

# Activate it
# macOS / Linux
source venv/bin/activate

# Windows (PowerShell)
.\venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## 2. Configure Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Open `.env` and fill in the required values:

```dotenv
# Django settings
SECRET_KEY=your-secret-key-here   # Generate one: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database — must be a valid PostgreSQL connection URL
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/multitenant_saas
```

Key variables explained:

| Variable        | Description                                                           | Default               |
| --------------- | --------------------------------------------------------------------- | --------------------- |
| `SECRET_KEY`    | Django cryptographic signing key — **must be unique per environment** | (none — required)     |
| `DEBUG`         | Enables debug mode and detailed error pages                           | `True`                |
| `ALLOWED_HOSTS` | Comma-separated list of allowed hostnames                             | `localhost,127.0.0.1` |
| `DATABASE_URL`  | Full PostgreSQL connection URL                                        | (none — required)     |

> **Note:** `DATABASE_URL` is parsed from a single URL string. The format is `postgresql://<user>:<password>@<host>:<port>/<dbname>`.

---

## 3. Set Up the Database

Create the PostgreSQL database:

```bash
# Connect to PostgreSQL as the postgres superuser
psql -U postgres

# Inside psql, create the database
CREATE DATABASE multitenant_saas;
\q
```

Run Django migrations to create all tables:

```bash
python manage.py migrate
```

You should see output like:

```
Operations to perform:
  Apply all migrations: admin, auth, authentication, contenttypes, core, sessions, tenants, widgets
Running migrations:
  Applying contenttypes.0001_initial... OK
  Applying authentication.0001_initial... OK
  ...
```

---

## 4. Run the Development Server

```bash
python manage.py runserver
```

The server starts at `http://127.0.0.1:8000`. Verify it's healthy:

```bash
curl http://127.0.0.1:8000/health
# {"status": "healthy", "database": "healthy"}
```

---

## 5. Create Your First Tenant and User

Tenant registration is the entry point — no authentication required. Send a `POST` request to create a tenant and its initial admin user:

```bash
curl -X POST http://127.0.0.1:8000/api/tenants/register/ \
  -H "Content-Type: application/json" \
  -d '{
    "identifier": "acme-corp",
    "admin_email": "admin@acme.com"
  }'
```

A successful response returns the tenant ID and temporary admin credentials:

```json
{
  "tenant_id": "acme-corp",
  "admin_username": "admin",
  "admin_password": "Tmp$ecret42!"
}
```

> **Important:** Save the `admin_password` — it is only shown once. Change it after your first login.

### Log In and Get a JWT Token

Use the admin credentials to obtain a JWT access token:

```bash
curl -X POST http://127.0.0.1:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "Tmp$ecret42!",
    "tenant_id": "acme-corp"
  }'
```

Response:

```json
{
  "access_token": "<jwt-access-token>",
  "refresh_token": "<jwt-refresh-token>",
  "user_id": "<user-uuid>",
  "tenant_id": "acme-corp",
  "role": "admin"
}
```

Use the `access_token` value in the `Authorization` header for all subsequent requests:

```bash
export TOKEN="<jwt-access-token>"

curl http://127.0.0.1:8000/api/tenants/config/ \
  -H "Authorization: Bearer $TOKEN"
```

---

## 6. Test the API with Swagger UI

Open your browser and navigate to:

```
http://127.0.0.1:8000/api/docs/
```

The interactive Swagger UI lists all available endpoints grouped by tag:

- **auth** — login, token refresh, API key management
- **tenants** — registration, deletion, subscription, audit logs
- **widgets** — example tenant-isolated CRUD resource
- **system** — health check, OpenAPI schema

### Authenticate in Swagger UI

1. Click the **Authorize** button (top right).
2. Under **BearerAuth**, paste your JWT access token (without the `Bearer ` prefix).
3. Click **Authorize** then **Close**.

All subsequent requests from Swagger UI will include the token automatically.

### Try a Request

1. Expand **GET /api/widgets/** under the `widgets` tag.
2. Click **Try it out** → **Execute**.
3. You should receive a `200` response with an empty list (no widgets yet).

---

## Next Steps

- **Create a widget** — `POST /api/widgets/` to see tenant-isolated CRUD in action.
- **Generate an API key** — `POST /api/auth/api-keys/` for programmatic access using the `X-API-Key` header.
- **Explore the architecture** — read `docs/developer-guide/` for extension points, code patterns, and ADRs.
- **Run the test suite** — `pytest` to verify everything is working correctly.
- **Scaffold a new resource** — `python manage.py scaffold_resource <ResourceName>` to generate a new tenant-isolated CRUD resource following the Widget pattern.
