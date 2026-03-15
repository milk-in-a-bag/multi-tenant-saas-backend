"""
Custom DRF exception handler for consistent error response formatting.

All error responses follow the shape:
    {"error": {"code": "...", "message": "...", "details": {...}}}
"""
from rest_framework.views import exception_handler
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    PermissionDenied,
    ValidationError,
    NotFound,
)
from rest_framework.response import Response
from rest_framework import status


def custom_exception_handler(exc, context):
    """
    Custom exception handler that formats all DRF error responses consistently.
    """
    # Let DRF handle the exception first to get a base response
    response = exception_handler(exc, context)

    if response is None:
        # Unhandled exception (500)
        error_body = {
            'error': {
                'code': 'INTERNAL_ERROR',
                'message': 'An internal error occurred',
                'details': {},
            }
        }
        return Response(error_body, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # Preserve Retry-After header if present (set by rate-limit middleware)
    retry_after = response.get('Retry-After')

    error_body = _build_error_body(exc)

    formatted = Response(error_body, status=response.status_code)

    if retry_after is not None:
        formatted['Retry-After'] = retry_after

    return formatted


def _build_error_body(exc):
    """Build the standardised error payload for a given exception."""
    if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
        return {
            'error': {
                'code': 'AUTHENTICATION_FAILED',
                'message': 'Authentication credentials were not provided or are invalid',
                'details': {},
            }
        }

    if isinstance(exc, PermissionDenied):
        return {
            'error': {
                'code': 'PERMISSION_DENIED',
                'message': str(exc.detail) if exc.detail else 'Permission denied.',
                'details': {},
            }
        }

    if isinstance(exc, ValidationError):
        details = exc.detail if isinstance(exc.detail, dict) else {'non_field_errors': exc.detail}
        return {
            'error': {
                'code': 'VALIDATION_ERROR',
                'message': 'Invalid input.',
                'details': details,
            }
        }

    if isinstance(exc, NotFound):
        return {
            'error': {
                'code': 'NOT_FOUND',
                'message': 'The requested resource was not found',
                'details': {},
            }
        }

    # Generic fallback for any other DRF exception
    return {
        'error': {
            'code': 'ERROR',
            'message': str(exc.detail) if hasattr(exc, 'detail') else str(exc),
            'details': {},
        }
    }
