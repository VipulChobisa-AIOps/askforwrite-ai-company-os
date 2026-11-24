"""Email dispatch providers: Mock, SMTP (RFC 5322), Resend HTTPS API, and Brevo HTTPS API.

HTTPS transactional providers (Resend / Brevo on port 443) work natively on PaaS hosts
such as Render Free tier that block outbound SMTP ports 25/465/587, and avoid shared-relay
MailChannels spam blocks while keeping strict staging/simulation isolation.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import urllib.error
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
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


def _is_simulation_environment() -> bool:
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    ext_disabled = os.getenv("ENABLE_EXTERNAL_SIDE_EFFECTS", "").strip().lower() in ("0", "false", "no")
    sim_only = os.getenv("SIMULATION_ONLY", "").strip().lower() in ("1", "true", "yes")
    smtp_mode = os.getenv("SMTP_MODE", "").strip().lower()
    return (
        ext_disabled
        or sim_only
        or app_env in ("staging", "simulation")
        or smtp_mode in ("sandbox", "sandbox_sink", "sink", "mock")
    )


def _record_simulated(provider_tag: str, recipient_email: str, subject: str, sender: str, body_text: str) -> dict[str, object]:
    from app.services.execution_guard import record_simulated_dispatch

    rec = record_simulated_dispatch(
        provider_tag,
        recipient_email,
        {"subject": subject, "sender": sender, "body_preview": body_text[:120]},
    )
    return {
        "provider": f"{provider_tag}_simulation",
        "status": "simulated",
        "simulated": True,
        "recipient": recipient_email,
        "sender": sender,
        "dispatch_id": rec["dispatch_id"],
    }


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
                "Configure RESEND_API_KEY, BREVO_API_KEY, or SMTP credentials (SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD)."
            )

        sender = from_email or os.getenv("OUTREACH_FROM_EMAIL", "info@askforwrite.in")
        message = DispatchedMessage(
            recipient_email=recipient_email,
            subject=subject,
            body_text=body_text,
            from_email=sender,
        )
        self.sent_messages.append(message)
        try:
            from app.services.execution_guard import record_simulated_dispatch

            record_simulated_dispatch(
                "hostinger_smtp",
                recipient_email,
                {"subject": subject, "sender": sender, "body_preview": body_text[:120]},
            )
        except Exception:
            pass
        logger.info("MockEmailDispatcher (SIMULATED) dispatched to %s with subject: %s", recipient_email, subject)
        return {
            "provider": "mock",
            "status": "simulated_delivered",
            "simulated": True,
            "recipient": recipient_email,
            "sender": sender,
            "message_id": f"mock-{len(self.sent_messages)}",
        }


class ResendEmailDispatcher:
    """HTTPS transactional email dispatcher using Resend API (port 443, Render Free-tier compatible)."""

    API_URL = "https://api.resend.com/emails"

    def __init__(self, api_key: str | None = None, default_sender: str | None = None) -> None:
        self.api_key = (api_key or os.getenv("RESEND_API_KEY", "")).strip()
        self.default_sender = default_sender or os.getenv("OUTREACH_FROM_EMAIL", "info@askforwrite.in")

    def send(
        self,
        recipient_email: str,
        subject: str,
        body_text: str,
        from_email: str | None = None,
    ) -> dict[str, object]:
        sender = from_email or self.default_sender
        if _is_simulation_environment():
            return _record_simulated("resend_https", recipient_email, subject, sender, body_text)
        if not self.api_key:
            raise RuntimeError("Resend HTTPS dispatch failure: RESEND_API_KEY is not configured")

        payload = {
            "from": sender,
            "to": [recipient_email],
            "subject": subject,
            "text": body_text,
            "reply_to": sender,
            "headers": {"List-Unsubscribe": f"<mailto:{sender}?subject=unsubscribe>"},
        }
        req = urllib.request.Request(
            self.API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "AskforWrite-OS-Mailer/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:  # nosec B310
                body = json.loads(resp.read().decode("utf-8", errors="replace"))
            return {
                "provider": "resend",
                "status": "delivered",
                "recipient": recipient_email,
                "sender": sender,
                "message_id": str(body.get("id") or ""),
            }
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")[:300]
            logger.error("Resend API error %s: %s", exc.code, err_body)
            raise RuntimeError(f"Resend HTTPS dispatch failure (HTTP {exc.code}): {err_body}") from exc
        except Exception as exc:
            logger.error("Failed to send email via Resend HTTPS API: %s", exc)
            raise RuntimeError(f"Resend HTTPS dispatch failure: {exc}") from exc


class BrevoEmailDispatcher:
    """HTTPS transactional email dispatcher using Brevo v3 SMTP API (port 443, Render Free-tier compatible)."""

    API_URL = "https://api.brevo.com/v3/smtp/email"

    def __init__(self, api_key: str | None = None, default_sender: str | None = None) -> None:
        self.api_key = (api_key or os.getenv("BREVO_API_KEY", "")).strip()
        self.default_sender = default_sender or os.getenv("OUTREACH_FROM_EMAIL", "info@askforwrite.in")
        self.sender_name = os.getenv("OUTREACH_FROM_NAME", "AskforWrite AI Solutions")

    def send(
        self,
        recipient_email: str,
        subject: str,
        body_text: str,
        from_email: str | None = None,
    ) -> dict[str, object]:
        sender = from_email or self.default_sender
        if _is_simulation_environment():
            return _record_simulated("brevo_https", recipient_email, subject, sender, body_text)
        if not self.api_key:
            raise RuntimeError("Brevo HTTPS dispatch failure: BREVO_API_KEY is not configured")

        payload = {
            "sender": {"name": self.sender_name, "email": sender},
            "to": [{"email": recipient_email}],
            "replyTo": {"email": sender, "name": self.sender_name},
            "subject": subject,
            "textContent": body_text,
            "headers": {"List-Unsubscribe": f"<mailto:{sender}?subject=unsubscribe>"},
        }
        req = urllib.request.Request(
            self.API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "AskforWrite-OS-Mailer/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:  # nosec B310
                body = json.loads(resp.read().decode("utf-8", errors="replace"))
            return {
                "provider": "brevo",
                "status": "delivered",
                "recipient": recipient_email,
                "sender": sender,
                "message_id": str(body.get("messageId") or ""),
            }
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")[:300]
            logger.error("Brevo API error %s: %s", exc.code, err_body)
            raise RuntimeError(f"Brevo HTTPS dispatch failure (HTTP {exc.code}): {err_body}") from exc
        except Exception as exc:
            logger.error("Failed to send email via Brevo HTTPS API: %s", exc)
            raise RuntimeError(f"Brevo HTTPS dispatch failure: {exc}") from exc


class SmtpEmailDispatcher:
    """Standard library SMTP email dispatcher with RFC 5322 deliverability headers."""

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
        if _is_simulation_environment():
            return _record_simulated("smtp_email", recipient_email, subject, sender, body_text)

        domain = sender.split("@")[-1] if "@" in sender else "askforwrite.in"
        msg_id = make_msgid(domain=domain)
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = recipient_email
        msg["Reply-To"] = sender
        msg["Date"] = formatdate(localtime=False)
        msg["Message-ID"] = msg_id
        msg["List-Unsubscribe"] = f"<mailto:{sender}?subject=unsubscribe>"
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
                "message_id": msg_id,
            }
        except Exception as exc:
            logger.error("Failed to send email via SMTP: %s", exc)
            raise RuntimeError(f"SMTP dispatch failure: {exc}") from exc


_default_mock_dispatcher = MockEmailDispatcher()


def get_email_dispatcher() -> EmailDispatcher:
    """Factory to retrieve configured email dispatcher based on environment settings.

    Supports HTTPS transactional APIs (Resend, Brevo on port 443) for PaaS environments
    that block outbound SMTP ports, plus standard SMTP and strict staging/test mocking.
    """
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    raw_provider = os.getenv("OUTREACH_DISPATCH_PROVIDER", "").strip().lower()
    resend_key = os.getenv("RESEND_API_KEY", "").strip()
    brevo_key = os.getenv("BREVO_API_KEY", "").strip()
    smtp_host = os.getenv("SMTP_HOST", "").strip()

    if _is_simulation_environment():
        return _default_mock_dispatcher

    if raw_provider == "resend":
        if not resend_key and app_env == "production":
            raise RuntimeError("Production OUTREACH_DISPATCH_PROVIDER=resend requires RESEND_API_KEY.")
        return ResendEmailDispatcher()
    if raw_provider == "brevo":
        if not brevo_key and app_env == "production":
            raise RuntimeError("Production OUTREACH_DISPATCH_PROVIDER=brevo requires BREVO_API_KEY.")
        return BrevoEmailDispatcher()

    if raw_provider in ("", "auto"):
        if resend_key:
            return ResendEmailDispatcher()
        if brevo_key:
            return BrevoEmailDispatcher()
        if smtp_host:
            return SmtpEmailDispatcher()
        if app_env == "production":
            raise RuntimeError(
                "Production environment requires RESEND_API_KEY, BREVO_API_KEY, or SMTP_HOST. "
                "Simulated / mock dispatchers are strictly disabled in production."
            )
        return _default_mock_dispatcher

    if app_env == "production":
        if raw_provider != "smtp" or not smtp_host:
            raise RuntimeError(
                "Production environment requires OUTREACH_DISPATCH_PROVIDER=resend|brevo|smtp "
                "with corresponding credentials. Simulated / mock dispatchers are strictly disabled in production."
            )
        return SmtpEmailDispatcher()

    if raw_provider == "smtp" and smtp_host:
        return SmtpEmailDispatcher()
    return _default_mock_dispatcher
