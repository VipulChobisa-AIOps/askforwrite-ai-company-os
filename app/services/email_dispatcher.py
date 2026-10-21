"""Email dispatch provider: mock and SMTP implementations with factory."""

from __future__ import annotations

import logging
import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class DispatchedMessage:
    recipient_email: str
    subject: str
    body_text: str
    from_email: str
    channel: str = "email"


class EmailDispatcher(Protocol):
    """Protocol for sending outbound customer outreach messages."""

    def send(
        self,
        recipient_email: str,
        subject: str,
        body_text: str,
        from_email: str | None = None,
    ) -> dict[str, object]:
        """Send message and return delivery receipt metadata."""
        ...


class MockEmailDispatcher:
    """In-memory mock dispatcher for testing, staging, and development."""

    def __init__(self) -> None:
        self.sent_messages: list[DispatchedMessage] = []

    def send(
        self,
        recipient_email: str,
        subject: str,
        body_text: str,
        from_email: str | None = None,
    ) -> dict[str, object]:
        app_env = os.getenv("APP_ENV", "development").lower()
        if app_env == "production":
            raise RuntimeError(
                "Mock email dispatcher is prohibited in production (APP_ENV=production). "
                "Configure real SMTP credentials (SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD)."
            )

        sender = from_email or os.getenv("OUTREACH_FROM_EMAIL", "info@askforwrite.in")
        message = DispatchedMessage(
            recipient_email=recipient_email,
            subject=subject,
            body_text=body_text,
            from_email=sender,
        )
        self.sent_messages.append(message)
        logger.info("MockEmailDispatcher (SIMULATED) dispatched to %s with subject: %s", recipient_email, subject)
        return {
            "provider": "mock",
            "status": "simulated_delivered",
            "simulated": True,
            "recipient": recipient_email,
            "sender": sender,
            "message_id": f"mock-{len(self.sent_messages)}",
        }



class SmtpEmailDispatcher:
    """Standard library SMTP email dispatcher."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
        default_sender: str | None = None,
    ) -> None:
        self.host = host or os.getenv("SMTP_HOST", "localhost")
        self.port = port or int(os.getenv("SMTP_PORT", "587"))
        self.username = username or os.getenv("SMTP_USERNAME") or os.getenv("SMTP_USER", "")
        self.password = password or os.getenv("SMTP_PASSWORD", "")
        self.use_tls = use_tls
        self.default_sender = default_sender or os.getenv("OUTREACH_FROM_EMAIL", "info@askforwrite.in")

    def send(
        self,
        recipient_email: str,
        subject: str,
        body_text: str,
        from_email: str | None = None,
    ) -> dict[str, object]:
        sender = from_email or self.default_sender
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient_email
        msg.set_content(body_text)

        try:
            if self.port == 465:
                with smtplib.SMTP_SSL(self.host, self.port, timeout=10.0) as server:
                    if self.username and self.password:
                        server.login(self.username, self.password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=10.0) as server:
                    if self.use_tls:
                        server.starttls()
                    if self.username and self.password:
                        server.login(self.username, self.password)
                    server.send_message(msg)
            return {
                "provider": "smtp",
                "status": "delivered",
                "recipient": recipient_email,
                "sender": sender,
            }
        except Exception as exc:
            logger.error("Failed to send email via SMTP: %s", exc)
            raise RuntimeError(f"SMTP dispatch failure: {exc}") from exc


_default_mock_dispatcher = MockEmailDispatcher()


def get_email_dispatcher() -> EmailDispatcher:
    """Factory to retrieve configured email dispatcher based on environment settings."""
    app_env = os.getenv("APP_ENV", "development").lower()
    provider = os.getenv("OUTREACH_DISPATCH_PROVIDER", "smtp" if app_env == "production" else "mock").lower()

    if app_env == "production":
        if provider != "smtp" or not os.getenv("SMTP_HOST"):
            raise RuntimeError(
                "Production environment requires OUTREACH_DISPATCH_PROVIDER=smtp and a valid SMTP_HOST. "
                "Simulated / mock dispatchers are strictly disabled in production."
            )
        return SmtpEmailDispatcher()

    if provider == "smtp" and os.getenv("SMTP_HOST"):
        return SmtpEmailDispatcher()
    return _default_mock_dispatcher

