"""
Authentication API views
"""

from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .permissions import IsAdmin
from .serializers import LoginSerializer, UpdateProfileSerializer
from .services import AuthService

# ---------------------------------------------------------------------------
# Inline response serializers used only for schema documentation
# ---------------------------------------------------------------------------

_LoginResponseSerializer = inline_serializer(
    name="LoginResponse",
    fields={
        "access_token": serializers.CharField(help_text="JWT access token (expires in 1 hour)"),
        "refresh_token": serializers.CharField(help_text="JWT refresh token"),
        "user_id": serializers.UUIDField(help_text="Authenticated user UUID"),
        "tenant_id": serializers.CharField(help_text="Tenant identifier"),
        "role": serializers.ChoiceField(choices=["admin", "user", "read_only"]),
    },
)

_APIKeyResponseSerializer = inline_serializer(
    name="APIKeyResponse",
    fields={
        "key_id": serializers.UUIDField(help_text="API key UUID (use for revocation)"),
        "api_key": serializers.CharField(help_text="Plaintext API key — shown only once, store securely"),
        "tenant_id": serializers.CharField(),
        "user_id": serializers.UUIDField(),
        "created_at": serializers.DateTimeField(),
    },
)

_ErrorSerializer = inline_serializer(
    name="AuthError",
    fields={
        "error": inline_serializer(
            name="AuthErrorDetail",
            fields={
                "code": serializers.CharField(),
                "message": serializers.CharField(),
                "details": serializers.DictField(child=serializers.CharField()),
            },
        )
    },
)

_RevokeResponseSerializer = inline_serializer(
    name="RevokeAPIKeyResponse",
    fields={"message": serializers.CharField()},
)

_ProfileSerializer = inline_serializer(
    name="ProfileResponse",
    fields={
        "user_id": serializers.UUIDField(),
        "username": serializers.CharField(),
        "email": serializers.EmailField(),
        "role": serializers.ChoiceField(choices=["admin", "user", "read_only"]),
    },
)

_RATE_LIMIT_NOTE = (
    "\n\n**Rate limiting:** This endpoint counts against the tenant's hourly request quota "
    "(100 / 1 000 / 10 000 req/hr for free / professional / enterprise tiers). "
    "Exceeding the quota returns `429 Too Many Requests` with a `Retry-After` header."
)

_TENANT_ISOLATION_NOTE = (
    "\n\n**Tenant isolation:** All data is scoped to the tenant embedded in the "
    "authentication credential. Cross-tenant access is rejected."
)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


@extend_schema(
    tags=["auth"],
    summary="Login — obtain JWT tokens",
    description=(
        "Authenticate with tenant ID, username, and password. "
        "Returns a short-lived JWT access token (1 hour) and a refresh token.\n\n"
        "Error messages are intentionally generic to avoid revealing which "
        "credential was incorrect." + _RATE_LIMIT_NOTE
    ),
    request=LoginSerializer,
    responses={
        200: OpenApiResponse(response=_LoginResponseSerializer, description="Authentication successful"),
        400: OpenApiResponse(response=_ErrorSerializer, description="Invalid request body"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Invalid credentials"),
        429: OpenApiResponse(description="Rate limit exceeded — see Retry-After header"),
    },
    examples=[
        OpenApiExample(
            "Login request",
            value={"tenant_id": "acme-corp", "username": "alice", "password": "secret"},
            request_only=True,
        ),
        OpenApiExample(
            "Successful login",
            value={
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "tenant_id": "acme-corp",
                "role": "admin",
            },
            response_only=True,
            status_codes=["200"],
        ),
    ],
    auth=[],
)
@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    """
    Authenticate user and return JWT tokens

    POST /api/auth/login/
    {
        "tenant_id": "my-company",
        "username": "admin@company.com",
        "password": "password123"
    }
    """
    serializer = LoginSerializer(data=request.data)
    if serializer.is_valid():
        try:
            ip_address = request.META.get("REMOTE_ADDR")
            result = AuthService.authenticate_user(
                tenant_id=serializer.validated_data["tenant_id"],
                username=serializer.validated_data["username"],
                password=serializer.validated_data["password"],
                ip_address=ip_address,
            )
            return Response(result, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({"error": e.detail}, status=status.HTTP_401_UNAUTHORIZED)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=["auth"],
    summary="Generate API key (admin only)",
    description=(
        "Generate a new cryptographically secure API key for a user within the "
        "authenticated tenant. Only admin users may call this endpoint.\n\n"
        "The plaintext key is returned **once** — it is never stored and cannot "
        "be retrieved again. Store it securely immediately." + _TENANT_ISOLATION_NOTE + _RATE_LIMIT_NOTE
    ),
    request=inline_serializer(
        name="GenerateAPIKeyRequest",
        fields={"user_id": serializers.UUIDField(help_text="UUID of the user to generate a key for")},
    ),
    responses={
        201: OpenApiResponse(response=_APIKeyResponseSerializer, description="API key created"),
        400: OpenApiResponse(response=_ErrorSerializer, description="Invalid request"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Not authenticated"),
        403: OpenApiResponse(response=_ErrorSerializer, description="Admin role required"),
        429: OpenApiResponse(description="Rate limit exceeded — see Retry-After header"),
    },
    examples=[
        OpenApiExample(
            "Generate key request",
            value={"user_id": "550e8400-e29b-41d4-a716-446655440000"},
            request_only=True,
        ),
        OpenApiExample(
            "API key created",
            value={
                "key_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "api_key": "sk_live_abc123...",
                "created_at": "2026-03-15T12:00:00Z",
            },
            response_only=True,
            status_codes=["201"],
        ),
    ],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsAdmin])
def generate_api_key(request):
    """
    Generate API key for a user (admin only)

    POST /api/auth/api-keys/
    {
        "user_id": "uuid-of-user"
    }
    """
    user_id = request.data.get("user_id")

    if not user_id:
        return Response({"error": "user_id is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        result = AuthService.generate_api_key(
            tenant_id=request.user.tenant_id, user_id=user_id, requesting_user_id=str(request.user.id)
        )
        return Response(result, status=status.HTTP_201_CREATED)
    except ValidationError as e:
        return Response({"error": e.detail}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=["auth"],
    summary="Revoke API key (admin only)",
    description=(
        "Permanently revoke an API key. Once revoked the key is rejected on all "
        "subsequent requests. Only admin users may revoke keys within their tenant."
        + _TENANT_ISOLATION_NOTE
        + _RATE_LIMIT_NOTE
    ),
    responses={
        200: OpenApiResponse(response=_RevokeResponseSerializer, description="Key revoked"),
        400: OpenApiResponse(response=_ErrorSerializer, description="Invalid key ID or key not found"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Not authenticated"),
        403: OpenApiResponse(response=_ErrorSerializer, description="Admin role required"),
        429: OpenApiResponse(description="Rate limit exceeded — see Retry-After header"),
    },
    examples=[
        OpenApiExample(
            "Revoke success",
            value={"message": "API key revoked successfully"},
            response_only=True,
            status_codes=["200"],
        ),
    ],
)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated, IsAdmin])
def revoke_api_key(request, key_id):
    """
    Revoke an API key (admin only)

    DELETE /api/auth/api-keys/{key_id}/
    """
    try:
        AuthService.revoke_api_key(
            tenant_id=request.user.tenant_id, key_id=key_id, requesting_user_id=str(request.user.id)
        )
        return Response({"message": "API key revoked successfully"}, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response({"error": e.detail}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    tags=["auth"],
    summary="Get own profile",
    description="Returns the authenticated user's profile — useful if you've forgotten your username.",
    responses={
        200: OpenApiResponse(response=_ProfileSerializer, description="Profile data"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Not authenticated"),
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    """
    GET /api/auth/me/
    Returns the current user's profile.
    """
    user = request.user
    return Response(
        {
            "user_id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role,
        },
        status=status.HTTP_200_OK,
    )


@extend_schema(
    tags=["auth"],
    summary="Update own profile (username / password)",
    description=(
        "Update your username and/or password. "
        "Changing the password requires supplying `current_password` for verification. "
        "You can also log in with your email if you ever forget your username."
    ),
    request=UpdateProfileSerializer,
    responses={
        200: OpenApiResponse(response=_ProfileSerializer, description="Updated profile"),
        400: OpenApiResponse(response=_ErrorSerializer, description="Validation error"),
        401: OpenApiResponse(response=_ErrorSerializer, description="Not authenticated"),
    },
    examples=[
        OpenApiExample(
            "Change password",
            value={"current_password": "old-secret", "new_password": "new-secret-123"},
            request_only=True,
        ),
        OpenApiExample(
            "Change username",
            value={"username": "my-new-name"},
            request_only=True,
        ),
    ],
)
@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_me(request):
    """
    PATCH /api/auth/me/
    Update the authenticated user's username and/or password.
    """
    serializer = UpdateProfileSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        result = AuthService.update_profile(
            user=request.user,
            username=serializer.validated_data.get("username"),
            current_password=serializer.validated_data.get("current_password"),
            new_password=serializer.validated_data.get("new_password"),
        )
        return Response(result, status=status.HTTP_200_OK)
    except ValidationError as e:
        return Response({"error": e.detail}, status=status.HTTP_400_BAD_REQUEST)
