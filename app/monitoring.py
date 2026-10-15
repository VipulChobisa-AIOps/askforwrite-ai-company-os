"""Sentry error tracking and performance monitoring integration."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("app.monitoring")


def init_sentry() -> bool:
    """Initialize Sentry SDK if SENTRY_DSN is provided.

    Gracefully no-ops if SENTRY_DSN is empty or sentry-sdk is not installed.
    """
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        logger.debug("SENTRY_DSN not configured; error tracking disabled.")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        app_env = os.environ.get("APP_ENV", "production").casefold()
        traces_sample_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.2"))
        profiles_sample_rate = float(os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.1"))
        release = os.environ.get("APP_VERSION", "0.2.0")

        sentry_sdk.init(
            dsn=dsn,
            environment=app_env,
            release=f"askforwrite-company-os@{release}",
            traces_sample_rate=traces_sample_rate,
            profiles_sample_rate=profiles_sample_rate,
            integrations=[
                FastApiIntegration(),
                SqlalchemyIntegration(),
            ],
            send_default_pii=False,
        )
        logger.info("Sentry monitoring initialized: env=%s, release=%s", app_env, release)
        return True
    except ImportError:
        logger.warning("SENTRY_DSN is configured, but sentry-sdk is not installed. Run 'pip install sentry-sdk[fastapi]'.")
        return False
    except Exception as exc:  # pragma: no cover
        logger.error("Failed to initialize Sentry: %s", exc)
        return False


def capture_exception(exc: Exception, **kwargs: Any) -> None:
    """Capture an exception with Sentry if available, otherwise log it."""
    try:
        import sentry_sdk
        sentry_sdk.capture_exception(exc, **kwargs)
    except ImportError:
        pass
    except Exception as e:
        logger.debug("Sentry capture_exception failed: %s", e)
