import pytest

from app.services.email_dispatcher import (
    MockEmailDispatcher,
    SmtpEmailDispatcher,
    get_email_dispatcher,
)


def test_get_email_dispatcher_returns_mock_in_development(monkeypatch):
    # Ensure dev environment
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("OUTREACH_DISPATCH_PROVIDER", raising=False)
    dispatcher = get_email_dispatcher()
    assert isinstance(dispatcher, MockEmailDispatcher)

def test_mock_email_dispatcher_send(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    dispatcher = MockEmailDispatcher()
    result = dispatcher.send(
        recipient_email="test@example.com",
        subject="Test",
        body_text="Hello",
    )
    assert result["provider"] == "mock"
    assert result["status"] == "simulated_delivered"
    assert result["recipient"] == "test@example.com"
    assert len(dispatcher.sent_messages) == 1

def test_get_email_dispatcher_returns_smtp_when_configured(monkeypatch):
    # Simulate production with SMTP config
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("OUTREACH_DISPATCH_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    dispatcher = get_email_dispatcher()
    assert isinstance(dispatcher, SmtpEmailDispatcher)

def test_smtp_email_dispatcher_send_failure(monkeypatch):
    # Use dummy SMTP config that will fail to connect
    monkeypatch.setenv("APP_ENV", "development")
    # Force provider to smtp even in dev
    monkeypatch.setenv("OUTREACH_DISPATCH_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "invalid-host")
    dispatcher = get_email_dispatcher()
    assert isinstance(dispatcher, SmtpEmailDispatcher)
    with pytest.raises(RuntimeError):
        dispatcher.send(
            recipient_email="test@example.com",
            subject="Fail",
            body_text="Test",
        )
