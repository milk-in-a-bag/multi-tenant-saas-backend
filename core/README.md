# Core Infrastructure

This module provides the core infrastructure for the multi-tenant SaaS backend, including tenant isolation, rate limiting, and audit logging.

## Components

### Data Isolator

The Data Isolator ensures complete tenant data separation at the database layer. See `data_isolator.py` for implementation details.

Key features:

- Automatic tenant_id filtering on all queries
- Automatic tenant_id association on all writes
- Custom model manager for tenant-isolated models
- Thread-local tenant context storage

### Middleware

#### TenantContextMiddleware

Extracts tenant context from authentication credentials (JWT tokens or API keys) and stores it in thread-local storage for use by the Data Isolator.

**Order**: Must come after Django's AuthenticationMiddleware

**Public endpoints** (skip tenant extraction):

- `/health` - Health check endpoint
- `/api/docs` - API documentation
- `/api/redoc` - ReDoc documentation
- `/api/schema` - OpenAPI schema
- `/api/tenants/register` - Tenant registration

#### RateLimitMiddleware

Enforces per-tenant rate limiting based on subscription tier.

**Order**: Must come after TenantContextMiddleware

**Rate limits by tier**:

- Free: 100 requests/hour
- Professional: 1,000 requests/hour
- Enterprise: 10,000 requests/hour

**Features**:

- Hourly rate limit windows (resets at start of each hour)
- Automatic downgrade to free tier limits for expired subscriptions
- Returns 429 status with Retry-After header when limit exceeded
- Tenant-isolated rate limit tracking
- Thread-safe with database-level locking

**Response format** (when rate limited):

```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit of 100 requests per hour exceeded"
  }
}
```

**Headers**:

- `Retry-After`: Seconds until rate limit resets (integer)

### Models

#### AuditLog

Tracks security-relevant events for compliance and monitoring.

Fields:

- `tenant` - Foreign key to Tenant
- `event_type` - Type of event (e.g., "authentication_success", "role_change")
- `user` - Foreign key to User (nullable)
- `timestamp` - When the event occurred
- `details` - JSONB field with event-specific data
- `ip_address` - IP address of the request (nullable)

#### RateLimit

Tracks request counts for rate limiting.

Fields:

- `tenant` - Primary key, foreign key to Tenant
- `request_count` - Number of requests in current window
- `window_start` - Start of current hourly window

## Configuration

### Middleware Order

The middleware must be configured in the correct order in `settings.py`:

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Tenant context middleware - must come after authentication
    'core.middleware.TenantContextMiddleware',
    # Rate limiting middleware - must come after tenant context
    'core.middleware.RateLimitMiddleware',
]
```

### Customizing Rate Limits

To customize rate limits, modify the `TIER_LIMITS` dictionary in `RateLimitMiddleware`:

```python
class RateLimitMiddleware(MiddlewareMixin):
    TIER_LIMITS = {
        'free': 100,
        'professional': 1000,
        'enterprise': 10000,
    }
```

## Testing

Run the rate limiting tests:

```bash
python manage.py test core.tests.test_rate_limit_middleware
```

Or with pytest:

```bash
pytest core/tests/test_rate_limit_middleware.py -v
```

## Usage Example

The rate limiting is automatic and transparent to API endpoints. When a tenant exceeds their rate limit:

```python
# Client makes request
GET /api/widgets
Authorization: Bearer <jwt_token>

# Response when rate limited
HTTP/1.1 429 Too Many Requests
Retry-After: 1234
Content-Type: application/json

{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit of 100 requests per hour exceeded"
  }
}
```

Clients should:

1. Check for 429 status code
2. Read the `Retry-After` header
3. Wait the specified number of seconds before retrying
4. Implement exponential backoff for repeated rate limit errors

## Extension Points

### Custom Rate Limiting Strategies

To implement custom rate limiting logic:

1. Subclass `RateLimitMiddleware`
2. Override `process_request()` method
3. Update `MIDDLEWARE` setting to use your custom class

Example:

```python
class CustomRateLimitMiddleware(RateLimitMiddleware):
    def process_request(self, request):
        # Custom logic here
        # e.g., per-endpoint limits, burst limits, etc.
        return super().process_request(request)
```

### Per-Endpoint Rate Limits

To add per-endpoint rate limits, modify the middleware to check the request path:

```python
ENDPOINT_LIMITS = {
    '/api/widgets': 50,  # Lower limit for expensive endpoint
    '/api/search': 10,   # Very low limit for search
}

# In process_request():
endpoint_limit = self.ENDPOINT_LIMITS.get(request.path)
if endpoint_limit:
    limit = min(limit, endpoint_limit)
```

## Security Considerations

1. **Tenant Isolation**: Rate limits are strictly isolated per tenant
2. **Database Locking**: Uses `select_for_update()` to prevent race conditions
3. **Expired Subscriptions**: Automatically downgrade to free tier limits
4. **Public Endpoints**: Health checks and docs are not rate limited
5. **Error Handling**: Gracefully handles database errors without blocking requests

## Performance

- Rate limit checks add ~5-10ms per request (database query + update)
- Uses database-level locking to ensure accuracy
- Hourly windows minimize database writes
- Consider caching rate limit records in Redis for high-traffic scenarios

## Troubleshooting

### Rate limits not enforcing

1. Check middleware order in `settings.py`
2. Verify `TenantContextMiddleware` is setting tenant context
3. Check database for `RateLimit` records
4. Verify tenant subscription tier is correct

### Rate limits resetting unexpectedly

1. Check server timezone configuration (`USE_TZ = True`)
2. Verify `window_start` is being set correctly
3. Check for clock skew on distributed systems

### Performance issues

1. Add database indexes on `rate_limits` table
2. Consider moving to Redis for rate limit storage
3. Implement rate limit caching layer
4. Use connection pooling for database
