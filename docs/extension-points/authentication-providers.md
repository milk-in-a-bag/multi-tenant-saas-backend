# Extension Point: Custom Authentication Providers

**Requirement: 13.1**

This document explains how to add custom authentication providers beyond the built-in password (JWT) and API key methods.

---

## Overview

The system ships with two authentication backends:

| Provider   | Header                                              | Implementation               |
| ---------- | --------------------------------------------------- | ---------------------------- |
| JWT Bearer | `Authorization: Bearer <token>`                     | `rest_framework_simplejwt`   |
| API Key    | `Authorization: ApiKey <key>` or `X-API-Key: <key>` | `authentication/backends.py` |

You can add any additional provider — LDAP, SAML, OAuth 2.0, SSO, magic links — by implementing a DRF `BaseAuthentication` subclass and registering it in settings.

---

## Where to Make Changes

| File                         | What to change                                                                                                     |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `authentication/backends.py` | Add your new backend class                                                                                         |
| `config/settings.py`         | Register the backend in `REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']`                                         |
| `authentication/services.py` | Optionally extend `AuthService` with provider-specific helpers                                                     |
| `core/middleware.py`         | Optionally extend `TenantContextMiddleware._extract_tenant_from_*` if your provider carries the tenant differently |

---

## Extension Point Marker

```python
# EXTENSION_POINT: authentication-providers
# Add custom authentication providers here.
# Each provider must:
#   1. Subclass rest_framework.authentication.BaseAuthentication
#   2. Return (user, None) on success or raise AuthenticationFailed
#   3. Ensure the returned user has a .tenant_id attribute so
#      TenantContextMiddleware can set the thread-local tenant context
# See: docs/extension-points/authentication-providers.md
```

This comment lives at the top of `authentication/backends.py`.

---

## How Authentication Flows Through the System

```
Request
  └─ TenantContextMiddleware   ← extracts tenant_id from credential
       └─ RateLimitMiddleware  ← reads tenant_id from thread-local
            └─ DRF auth layer  ← calls each backend in order
                 └─ Your backend returns (user, None)
                      └─ RoleBasedPermission checks user.role
```

`TenantContextMiddleware` runs **before** DRF authentication. It extracts the tenant ID from the raw credential (JWT claim or API key hash lookup) so rate limiting can happen before the full auth check. If you add a provider that carries the tenant in a non-standard way, extend `_extract_tenant_from_*` in `core/middleware.py`.

---

## Example: LDAP Authentication Backend

```python
# authentication/backends.py

# EXTENSION_POINT: authentication-providers
import ldap3
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from authentication.models import User
from core.middleware import set_current_tenant


class LDAPAuthentication(BaseAuthentication):
    """
    Authenticate users against a corporate LDAP / Active Directory server.

    Expects the standard Authorization: Bearer <token> header where the
    token is a base64-encoded "tenant_id:username:password" triplet.
    (Adjust the credential format to match your LDAP setup.)
    """

    LDAP_SERVER = "ldap://ldap.example.com"
    LDAP_BASE_DN = "dc=example,dc=com"

    def authenticate(self, request):
        import base64

        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("LDAP "):
            return None  # Let other backends try

        try:
            raw = base64.b64decode(auth_header[5:]).decode()
            tenant_id, username, password = raw.split(":", 2)
        except Exception:
            raise AuthenticationFailed("Malformed LDAP credential header.")

        # Bind to LDAP
        server = ldap3.Server(self.LDAP_SERVER)
        user_dn = f"uid={username},{self.LDAP_BASE_DN}"
        conn = ldap3.Connection(server, user=user_dn, password=password)

        if not conn.bind():
            raise AuthenticationFailed("LDAP authentication failed.")

        # Map LDAP user to a local Django user (create on first login)
        user = self._get_or_create_user(tenant_id, username)
        return (user, None)

    def _get_or_create_user(self, tenant_id, username):
        """
        Find or create a local User record for the LDAP-authenticated user.
        Adjust the role mapping to match your LDAP group structure.
        """
        set_current_tenant(tenant_id)
        user, _ = User.objects.get_or_create(
            tenant_id=tenant_id,
            username=username,
            defaults={
                "email": f"{username}@example.com",
                "role": "user",
            },
        )
        return user
```

Register the backend in `config/settings.py`:

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "authentication.backends.LDAPAuthentication",   # ← add here
        "authentication.backends.APIKeyAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    # ...
}
```

---

## Example: OAuth 2.0 / Social Login Backend

```python
# authentication/backends.py

import requests
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from authentication.models import User
from core.middleware import set_current_tenant


class GoogleOAuthAuthentication(BaseAuthentication):
    """
    Validate a Google OAuth 2.0 access token and map it to a local user.

    Clients send:  Authorization: GoogleOAuth <google_access_token>
    The tenant is identified by the verified email domain.
    """

    GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
    # Map email domains to tenant IDs — customise for your deployment
    DOMAIN_TO_TENANT = {
        "acme.com": "acme-corp",
        "widgets.io": "widgets-inc",
    }

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("GoogleOAuth "):
            return None

        access_token = auth_header[len("GoogleOAuth "):]
        user_info = self._verify_google_token(access_token)
        tenant_id = self._resolve_tenant(user_info["email"])
        user = self._get_or_create_user(tenant_id, user_info)
        return (user, None)

    def _verify_google_token(self, token):
        resp = requests.get(
            self.GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if resp.status_code != 200:
            raise AuthenticationFailed("Invalid Google access token.")
        return resp.json()

    def _resolve_tenant(self, email):
        domain = email.split("@")[-1]
        tenant_id = self.DOMAIN_TO_TENANT.get(domain)
        if not tenant_id:
            raise AuthenticationFailed(f"No tenant configured for domain: {domain}")
        return tenant_id

    def _get_or_create_user(self, tenant_id, user_info):
        set_current_tenant(tenant_id)
        user, _ = User.objects.get_or_create(
            tenant_id=tenant_id,
            email=user_info["email"],
            defaults={
                "username": user_info.get("name", user_info["email"]),
                "role": "user",
            },
        )
        return user
```

---

## Tenant Context Requirement

Every authentication backend **must** ensure the returned `user` object has a `tenant_id` attribute. `TenantContextMiddleware` reads the tenant from the credential before DRF runs, but if your provider uses a non-standard header, extend the middleware:

```python
# core/middleware.py  (inside TenantContextMiddleware.process_request)

# EXTENSION_POINT: authentication-providers
# Add tenant extraction logic for custom providers here.
elif 'HTTP_X_SAML_ASSERTION' in request.META:
    tenant_id = self._extract_tenant_from_saml(request.META['HTTP_X_SAML_ASSERTION'])
```

---

## Testing Custom Providers

```python
# authentication/tests.py

from django.test import TestCase, RequestFactory
from unittest.mock import patch, MagicMock
from authentication.backends import LDAPAuthentication
from authentication.models import User
from tenants.models import Tenant
from django.utils import timezone
from datetime import timedelta


class LDAPAuthenticationTest(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            id="test-corp",
            subscription_tier="free",
            subscription_expiration=timezone.now() + timedelta(days=365),
        )
        self.factory = RequestFactory()
        self.backend = LDAPAuthentication()

    @patch("ldap3.Connection")
    def test_valid_ldap_credentials_return_user(self, mock_conn_cls):
        import base64
        mock_conn = MagicMock()
        mock_conn.bind.return_value = True
        mock_conn_cls.return_value = mock_conn

        credential = base64.b64encode(b"test-corp:alice:secret").decode()
        request = self.factory.get("/", HTTP_AUTHORIZATION=f"LDAP {credential}")

        user, _ = self.backend.authenticate(request)
        self.assertEqual(user.username, "alice")
        self.assertEqual(user.tenant_id, "test-corp")

    def test_non_ldap_header_returns_none(self):
        request = self.factory.get("/", HTTP_AUTHORIZATION="Bearer sometoken")
        result = self.backend.authenticate(request)
        self.assertIsNone(result)
```

---

## Related Files

- `authentication/backends.py` — existing `APIKeyAuthentication` to use as a reference
- `authentication/services.py` — `AuthService.authenticate_user` for the JWT flow
- `core/middleware.py` — `TenantContextMiddleware` tenant extraction
- `config/settings.py` — `REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']`
- `docs/developer-guide/architecture.md` — authentication flow sequence diagram
