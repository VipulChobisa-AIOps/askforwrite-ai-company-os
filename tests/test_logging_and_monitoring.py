"""Unit tests for structured JSON logging and Sentry monitoring."""

import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.logging_config import (
    DevFormatter,
    JsonFormatter,
    RequestLoggingMiddleware,
    configure_logging,
    get_logger,
)
from app.monitoring import capture_exception, init_sentry


def test_json_formatter_standard_record():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Test message %s",
        args=("arg1",),
        exc_info=None,
    )
    record.request_id = "req-123"
    record.duration_ms = 45.2
    record.method = "POST"
    record.path = "/v1/leads"
    record.status_code = 200

    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test_logger"
    assert parsed["message"] == "Test message arg1"
    assert parsed["request_id"] == "req-123"
    assert parsed["duration_ms"] == 45.2
    assert parsed["method"] == "POST"
    assert parsed["path"] == "/v1/leads"
    assert parsed["status_code"] == 200
    assert "timestamp" in parsed


def test_json_formatter_with_exception():
    formatter = JsonFormatter()
    try:
        raise ValueError("Something went wrong")
    except ValueError:
        import sys
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test_logger",
        level=logging.ERROR,
        pathname=__file__,
        lineno=20,
        msg="Operation failed",
        args=(),
        exc_info=exc_info,
    )
    output = formatter.format(record)
    parsed = json.loads(output)

    assert parsed["level"] == "ERROR"
    assert "ValueError: Something went wrong" in parsed["exception"]


def test_dev_formatter():
    formatter = DevFormatter()
    record = logging.LogRecord(
        name="dev_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=30,
        msg="Dev log",
        args=(),
        exc_info=None,
    )
    record.request_id = "req-987654321"
    output = formatter.format(record)
    assert "dev_logger" in output
    assert "Dev log" in output
    assert "req-9876" in output


def test_configure_logging_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    configure_logging()

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert len(root.handlers) > 0
    assert isinstance(root.handlers[0].formatter, JsonFormatter)


def test_configure_logging_development(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    configure_logging()

    root = logging.getLogger()
    assert len(root.handlers) > 0
    assert isinstance(root.handlers[0].formatter, DevFormatter)


def test_get_logger():
    logger = get_logger("custom_module")
    assert logger.name == "custom_module"


def test_init_sentry_no_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    result = init_sentry()
    assert result is False


def test_capture_exception_graceful():
    # Should not raise even if sentry is unconfigured
    try:
        raise RuntimeError("Test error")
    except RuntimeError as exc:
        capture_exception(exc)


def test_request_logging_middleware_integration():
    test_app = FastAPI()
    test_app.add_middleware(RequestLoggingMiddleware)

    @test_app.get("/ping")
    def ping():
        return {"status": "ok"}

    client = TestClient(test_app)
    response = client.get("/ping", headers={"X-Correlation-ID": "test-corr-id"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
