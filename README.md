# Multi-Tenant SaaS Backend

A production-ready Django-based multi-tenant SaaS starter kit with complete tenant isolation, authentication, authorization, and API management.

## Features

- Complete multi-tenant infrastructure with tenant isolation
- JWT-based authentication with 1-hour token expiration
- Role-based access control (admin, user, read_only)
- API key management for programmatic access
- Per-tenant rate limiting
- Comprehensive audit logging
- OpenAPI/Swagger documentation
- PostgreSQL database with proper indexing

## Technology Stack

- Django 5.0.1
- Django REST Framework 3.14.0
- PostgreSQL (via psycopg 3.2.3)
- JWT authentication (djangorestframework-simplejwt)
- OpenAPI documentation (drf-spectacular)
- Bcrypt password hashing

## Setup Instructions

### Prerequisites

- Python 3.11+
- PostgreSQL 12+

### Installation

1. Clone the repository
2. Create a virtual environment:

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Create a PostgreSQL database:

   ```sql
   CREATE DATABASE multitenant_saas;
   ```

5. Copy `.env.example` to `.env` and configure your database settings:

   ```bash
   cp .env.example .env
   ```

6. Run migrations:

   ```bash
   python manage.py migrate
   ```

7. Create a superuser:

   ```bash
   python manage.py createsuperuser
   ```

8. Run the development server:
   ```bash
   python manage.py runserver
   ```

## API Documentation

Once the server is running, access the interactive API documentation at:

- Swagger UI: http://localhost:8000/api/docs/
- OpenAPI Schema: http://localhost:8000/api/schema/

## Project Structure

```
├── config/              # Django project settings
├── core/                # Core utilities (audit logs, rate limiting)
├── tenants/             # Tenant management
├── authentication/      # User authentication and API keys
├── widgets/             # Example business logic
├── api/                 # API routing
└── requirements.txt     # Python dependencies
```

## Database Schema

### Core Tables

- **tenants**: Tenant organizations with subscription tiers
- **users**: User accounts with tenant isolation and roles
- **api_keys**: API keys for programmatic access
- **audit_logs**: Security event logging
- **rate_limits**: Per-tenant request throttling

All tables include proper indexes for tenant_id to ensure efficient queries.

## Security Features

- Bcrypt password hashing with cost factor 12
- JWT tokens with 1-hour expiration
- API key hashing (never stored in plaintext)
- Tenant data isolation at database level
- Role-based access control
- Comprehensive audit logging

## License

MIT License
