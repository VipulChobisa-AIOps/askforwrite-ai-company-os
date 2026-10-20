"""Structured JSON logging for production observability.

Provides:
- JSON-formatted log output in production (machine-parseable by Railway, Datadog, etc.)
- Human-readable colored output in development
- Automatic request context injection (request_id, correlation_id)
- Performance timing on every request
"""

import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class JsonFormatter(logging.Formatter):
    """Structured JSON log formatter for production environments."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add any extra fields attached to the record
        for key in ("request_id", "correlation_id", "method", "path",
                     "status_code", "duration_ms", "client_ip", "user_agent",
                     "org_id", "user_id", "task_id", "capability"):
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = value

        return json.dumps(log_entry, default=str)


class DevFormatter(logging.Formatter):
    """Human-readable colored formatter for development."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[41m",  # Red background
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        timestamp = datetime.now().strftime("%H:%M:%S")
        request_id = getattr(record, "request_id", None)
        rid_str = f" [{request_id[:8]}]" if request_id else ""
        return (
            f"{color}{timestamp} {record.levelname:8s}{self.RESET}"
            f"{rid_str} {record.name}: {record.getMessage()}"
        )


def configure_logging() -> None:
    """Configure structured logging based on APP_ENV.

    - production / staging → JSON to stdout (for Railway / Docker log aggregation)
    - development → colored human-readable output
    """
    app_env = os.environ.get("APP_ENV", "development").casefold()
    raw_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    valid_levels = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    log_level = raw_level if raw_level in valid_levels else "INFO"

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove any existing handlers
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)

    if app_env in ("production", "staging"):
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(DevFormatter())

    root_logger.addHandler(handler)

    # Quiet down noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    logger = logging.getLogger("app")
    logger.info("Logging configured: env=%s level=%s format=%s",
                app_env, log_level,
                "json" if app_env in ("production", "staging") else "dev")


def get_logger(name: str) -> logging.Logger:
    """Get a namespaced logger for a module.

    Usage:
        from app.logging_config import get_logger
        logger = get_logger(__name__)
        logger.info("Discovery completed", extra={"task_id": task.id})
    """
    return logging.getLogger(name)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every HTTP request with timing, status, and context."""

    async def dispatch(self, request: Request, call_next) -> Response:
        logger = logging.getLogger("app.http")
        start = time.perf_counter()

        # Extract context
        request_id = getattr(request.state, "request_id", None) if hasattr(request, "state") else None
        correlation_id = request.headers.get("X-Correlation-ID")

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.error(
                "%s %s -> 500 (%.1fms)",
                request.method, request.url.path, duration_ms,
                extra={
                    "request_id": request_id,
                    "correlation_id": correlation_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    "client_ip": request.client.host if request.client else None,
                },
                exc_info=True,
            )
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        status = response.status_code
        if not request_id and hasattr(request, "state"):
            request_id = getattr(request.state, "request_id", None)
        if not request_id:
            request_id = response.headers.get("X-Request-ID")

        log_extra = {
            "request_id": request_id,
            "correlation_id": correlation_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": status,
            "duration_ms": duration_ms,
            "client_ip": request.client.host if request.client else None,
        }

        # Keep logs concise: quiet during tests and healthchecks
        is_test = bool(os.environ.get("PYTEST_CURRENT_TEST"))
        if is_test or request.url.path in ("/health", "/", "/healthz"):
            logger.debug("%s %s -> %d (%.1fms)", request.method, request.url.path, status, duration_ms, extra=log_extra)
        elif status >= 500:
            logger.error("%s %s -> %d (%.1fms)", request.method, request.url.path, status, duration_ms, extra=log_extra)
        elif status >= 400:
            logger.warning("%s %s -> %d (%.1fms)", request.method, request.url.path, status, duration_ms, extra=log_extra)
        else:
            logger.info("%s %s -> %d (%.1fms)", request.method, request.url.path, status, duration_ms, extra=log_extra)

        return response

