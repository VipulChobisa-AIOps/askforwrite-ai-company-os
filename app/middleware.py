"""Production middleware: CORS, request-ID propagation, and rate limiting."""

import os
import time
import uuid
from collections import defaultdict
from collections.abc import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.logging_config import RequestLoggingMiddleware


def add_production_middleware(app: FastAPI) -> None:
    """Register all production middleware on the FastAPI app."""
    app.add_middleware(SecurityHeadersMiddleware)
    _add_cors(app)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestIdMiddleware)
    # Rate limiting only in non-development environments
    app_env = os.environ.get("APP_ENV", "development").casefold()
    if app_env != "development":
        app.add_middleware(RateLimitMiddleware)




# ── CORS ──────────────────────────────────────────────────────────────

def _add_cors(app: FastAPI) -> None:
    origins_raw = os.environ.get("ALLOWED_ORIGINS", "")
    if not origins_raw:
        # No CORS at all in production when origins are not configured
        return
    origins = [o.strip() for o in origins_raw.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "X-Correlation-ID", "Content-Type"],
        expose_headers=["X-Request-ID"],
        max_age=3600,
    )


# ── Security Headers ──────────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces strict production security headers across all HTTP responses."""

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)
        self.is_production = os.environ.get("APP_ENV", "development").casefold() == "production"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Baseline security headers for all endpoints
        headers = response.headers
        headers["X-Content-Type-Options"] = "nosniff"
        headers["X-Frame-Options"] = "SAMEORIGIN"
        headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        headers["Permissions-Policy"] = "geolocation=(self), camera=(self), microphone=()"
        headers["Content-Security-Policy"] = (
            "default-src 'self' 'unsafe-inline' https: data: blob:; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: https: blob:; "
            "connect-src 'self' https:;"
        )

        is_production = (
            os.environ.get("APP_ENV", "development").casefold() == "production"
            or self.is_production
        )
        if is_production:
            headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"

        return response


# ── Request ID ────────────────────────────────────────────────────────

class RequestIdMiddleware(BaseHTTPMiddleware):
    """Injects a unique X-Request-ID into every request/response cycle."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response



# ── Rate Limiting ─────────────────────────────────────────────────────

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Tenant-aware sliding-window rate limiter.

    Features:
    - Tier-based rate limits:
        - Enterprise: 2,400 req/min
        - Pro: 600 req/min
        - Starter & Modular: 120 req/min
        - Default/Free: 60 req/min
    - Caller identification:
        - X-Org-ID / Tenant ID
        - X-API-Key
        - Bearer Token Hash
        - Client IP fallback
    - Protection rules:
        - Approval decisions: 10 req/min
        - Authentication endpoints: 20 req/min
    - Standard response headers:
        - X-RateLimit-Limit
        - X-RateLimit-Remaining
        - Retry-After (on 429)
    """

    TIER_LIMITS: dict[str, int] = {
        "enterprise": 2400,
        "pro": 600,
        "starter": 120,
        "modular_field_ops": 120,
        "modular_marketing": 120,
        "modular_seo": 120,
        "modular_trust": 120,
        "free": 60,
    }

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)
        self._general_limit = int(os.environ.get("RATE_LIMIT_GENERAL", "60"))
        self._approval_limit = int(os.environ.get("RATE_LIMIT_APPROVAL", "10"))
        self._auth_limit = int(os.environ.get("RATE_LIMIT_AUTH", "20"))
        self._window = 60  # seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._redis_client = None
        redis_url = os.environ.get("REDIS_URL", "")
        if redis_url:
            try:
                import redis
                self._redis_client = redis.from_url(redis_url, decode_responses=True)
            except Exception:
                self._redis_client = None

    def _count_and_record(self, key: str) -> int:
        now = time.time()
        cutoff = now - self._window
        if self._redis_client:
            try:
                pipe = self._redis_client.pipeline()
                rkey = f"ratelimit:{key}"
                pipe.zremrangebyscore(rkey, 0, cutoff)
                pipe.zadd(rkey, {str(now): now})
                pipe.zcard(rkey)
                pipe.expire(rkey, self._window + 5)
                res = pipe.execute()
                return int(res[2])
            except Exception:
                pass

        # Fallback to in-memory sliding window
        mono_now = time.monotonic()
        mono_cutoff = mono_now - self._window
        self._buckets[key] = [t for t in self._buckets[key] if t > mono_cutoff]
        self._buckets[key].append(mono_now)
        return len(self._buckets[key])


    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Extract caller identity (Tenant Org ID > API Key > Bearer token > Client IP)
        org_id = request.headers.get("X-Org-ID")
        api_key = request.headers.get("X-API-Key")
        auth_header = request.headers.get("Authorization", "")
        org_tier = request.headers.get("X-Org-Tier", "").lower()

        if org_id:
            bucket_key = f"org:{org_id}"
        elif api_key:
            bucket_key = f"key:{api_key[:8]}"
        elif auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            bucket_key = f"token:{hash(token) % 10000000}"
        else:
            client_ip = request.client.host if request.client else "anon"
            bucket_key = f"ip:{client_ip}"

        path = request.url.path
        is_approval_decision = (
            "/v1/approvals/" in path
            and path.endswith("/decision")
            and request.method == "POST"
        )
        is_auth_endpoint = (
            path in ("/v1/auth/login", "/v1/auth/signup", "/v1/auth/register")
            and request.method == "POST"
        )

        # Determine dynamic limit
        if is_approval_decision:
            limit = self._approval_limit
        elif is_auth_endpoint:
            limit = self._auth_limit
        elif org_tier in self.TIER_LIMITS:
            limit = self.TIER_LIMITS[org_tier]
        else:
            limit = self._general_limit

        current = self._count_and_record(bucket_key)
        if current > limit:
            return Response(
                content='{"detail":"Rate limit exceeded. Try again later."}',
                status_code=429,
                media_type="application/json",
                headers={
                    "Retry-After": str(self._window),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - current))
        return response


