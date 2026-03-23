"""
Django settings for multi-tenant SaaS project.
"""

import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Security settings
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-change-this-in-production")
DEBUG = os.getenv("DEBUG", "True") == "True"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
# Allow Vercel deployment and alias URLs automatically
ALLOWED_HOSTS += [h for h in [os.getenv("VERCEL_URL")] if h]
ALLOWED_HOSTS += [".vercel.app"]

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party apps
    "corsheaders",
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    # Local apps
    "core",
    "tenants",
    "authentication",
    "widgets",
    "api",
]

MIDDLEWARE = [
    # SecurityMiddleware first for HTTPS redirects and security headers
    "django.middleware.security.SecurityMiddleware",
    # CorsMiddleware must be before CommonMiddleware to handle CORS preflight
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Tenant context middleware - must come after Django's AuthenticationMiddleware
    "core.middleware.TenantContextMiddleware",
    # Rate limiting middleware - must come after TenantContextMiddleware
    "core.middleware.RateLimitMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database configuration
tmpPostgres = urlparse(os.getenv("DATABASE_URL"))
_db_name = tmpPostgres.path.replace("/", "")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _db_name,
        "USER": tmpPostgres.username,
        "PASSWORD": tmpPostgres.password,
        "HOST": tmpPostgres.hostname,
        "PORT": 5432,
        "OPTIONS": dict(parse_qsl(tmpPostgres.query)),
        # Use the same database for tests (required for cloud databases like Neon
        # that don't support CREATE DATABASE)
        "TEST": {
            "NAME": _db_name,
        },
        # Disable server-side cursors to avoid psycopg3 cursor issues during test serialization
        "DISABLE_SERVER_SIDE_CURSORS": True,
    }
}

# Custom user model
AUTH_USER_MODEL = "authentication.User"

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django REST Framework configuration
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "authentication.backends.APIKeyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "api.exception_handler.custom_exception_handler",
}

# JWT configuration
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# drf-spectacular configuration
SPECTACULAR_SETTINGS = {
    "TITLE": "Multi-Tenant SaaS API",
    "DESCRIPTION": (
        "Production-ready multi-tenant SaaS backend with complete tenant isolation, "
        "JWT and API key authentication, role-based access control, rate limiting, "
        "and audit logging.\n\n"
        "## Authentication\n\n"
        "All endpoints (except `/health` and `/api/tenants/register/`) require authentication.\n\n"
        "**JWT Bearer Token** — obtain via `POST /api/auth/login/`, then pass as "
        "`Authorization: Bearer <token>`. Tokens expire after 1 hour.\n\n"
        "**API Key** — pass as `X-API-Key: <key>` header. Keys are generated by admins "
        "via `POST /api/auth/api-keys/`.\n\n"
        "## Tenant Isolation\n\n"
        "Every authenticated request is scoped to the tenant embedded in the JWT or "
        "associated with the API key. Data from other tenants is never returned.\n\n"
        "## Rate Limiting\n\n"
        "Requests are rate-limited per tenant per hour based on subscription tier:\n"
        "- **Free**: 100 req/hr\n"
        "- **Professional**: 1 000 req/hr\n"
        "- **Enterprise**: 10 000 req/hr\n\n"
        "When the limit is exceeded the API returns `429 Too Many Requests` with a "
        "`Retry-After` header indicating when the window resets."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Authentication schemes
    "SECURITY": [{"BearerAuth": []}, {"ApiKeyAuth": []}],
    "COMPONENTS": {
        "securitySchemes": {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "JWT token obtained from POST /api/auth/login/",
            },
            "ApiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": "API key generated by an admin via POST /api/auth/api-keys/",
            },
        },
    },
    # Schema generation options
    "SCHEMA_PATH_PREFIX": r"/api/",
    "SORT_OPERATIONS": False,
    "ENUM_GENERATE_CHOICE_DESCRIPTION": True,
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
    ],
    # Tags for grouping endpoints in Swagger UI
    "TAGS": [
        {"name": "auth", "description": "Authentication — login, JWT tokens, API key management"},
        {"name": "tenants", "description": "Tenant lifecycle — registration, deletion, subscription, audit logs"},
        {"name": "widgets", "description": "Widget CRUD — example tenant-isolated business resource"},
        {"name": "system", "description": "System endpoints — health check, OpenAPI schema"},
    ],
}

# Bcrypt password hasher configuration with cost factor 12
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# Configure bcrypt cost factor
BCRYPT_ROUNDS = 12

# CORS configuration
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5174").split(",")
CORS_ALLOW_CREDENTIALS = True

# Security headers
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_BROWSER_XSS_FILTER = True  # Adds X-XSS-Protection header
# HTTPS settings (enabled in production via environment)
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "False") == "True"
SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv("SECURE_HSTS_INCLUDE_SUBDOMAINS", "False") == "True"
SECURE_HSTS_PRELOAD = os.getenv("SECURE_HSTS_PRELOAD", "False") == "True"
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "False") == "True"
CSRF_COOKIE_SECURE = os.getenv("CSRF_COOKIE_SECURE", "False") == "True"
