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

    def _count_requests(self, key: str) -> int:
        now = time.monotonic()
        cutoff = now - self._window
        self._buckets[key] = [t for t in self._buckets[key] if t > cutoff]
        return len(self._buckets[key])

    def _record_request(self, key: str) -> None:
        self._buckets[key].append(time.monotonic())

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

        current = self._count_requests(bucket_key)
        if current >= limit:
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

        self._record_request(bucket_key)
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - current - 1))
        return response

