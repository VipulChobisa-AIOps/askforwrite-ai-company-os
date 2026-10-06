"""Production middleware: CORS, request-ID propagation, and rate limiting."""

import os
import time
import uuid
from collections import defaultdict
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware


def add_production_middleware(app: FastAPI) -> None:
    """Register all production middleware on the FastAPI app."""
    _add_cors(app)
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
    """Simple sliding-window rate limiter keyed by API key.

    Protects Owner approval endpoints with a stricter limit.
    Default: 60 requests/minute general, 10 requests/minute for approval decisions.
    """

    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)
        self._general_limit = int(os.environ.get("RATE_LIMIT_GENERAL", "60"))
        self._approval_limit = int(os.environ.get("RATE_LIMIT_APPROVAL", "10"))
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
        api_key = request.headers.get("X-API-Key", "anonymous")
        # Use first 8 chars as bucket key to avoid storing full secrets
        bucket_key = api_key[:8] if len(api_key) >= 8 else api_key

        # Determine limit based on path
        path = request.url.path
        is_approval_decision = (
            "/v1/approvals/" in path
            and path.endswith("/decision")
            and request.method == "POST"
        )
        limit = self._approval_limit if is_approval_decision else self._general_limit

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
        response.headers["X-RateLimit-Remaining"] = str(limit - current - 1)
        return response
