"""Authenticated client for the AskforWrite Native Field Force task capability."""

import os
from typing import Any

import httpx


class FieldForceNotConfigured(Exception):
    """Raised when the service URL or machine credential is missing."""


class FieldForceExecutionError(Exception):
    """Raised when the Field Force service rejects a task or verification fails."""


class FieldForceClient:
    def __init__(
        self,
        base_url: str,
        service_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 5.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    async def create_and_verify_task(
        self,
        *,
        title: str,
        description: str | None,
        assigned_to: str,
        due_date: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        if not self.base_url:
            raise FieldForceNotConfigured("FIELD_FORCE_BASE_URL is not configured")
        if len(self.service_token) < 32:
            raise FieldForceNotConfigured("FIELD_FORCE_SERVICE_TOKEN must contain at least 32 characters")

        headers = {
            "Authorization": f"Bearer {self.service_token}",
            "Idempotency-Key": idempotency_key,
            "X-Correlation-ID": correlation_id,
        }
        payload = {
            "title": title,
            "description": description,
            "assignedTo": assigned_to,
            "dueDate": due_date,
        }

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                created_response = await client.post(
                    "/api/agent/tasks",
                    headers=headers,
                    json=payload,
                )
                if created_response.status_code not in {200, 201}:
                    raise FieldForceExecutionError(
                        f"Field Force task creation failed with HTTP {created_response.status_code}"
                    )
                created = created_response.json()
                task_id = created.get("taskId")
                if not isinstance(task_id, str) or not task_id:
                    raise FieldForceExecutionError("Field Force response did not include taskId")

                status_response = await client.get(
                    f"/api/agent/tasks/{task_id}",
                    headers=headers,
                )
                if status_response.status_code != 200:
                    raise FieldForceExecutionError(
                        f"Field Force task verification failed with HTTP {status_response.status_code}"
                    )
                verified = status_response.json()
        except httpx.HTTPError as error:
            raise FieldForceExecutionError("Field Force task request failed before verification") from error

        if (
            verified.get("taskId") != task_id
            or verified.get("title") != title
            or verified.get("assignedTo") != assigned_to
            or verified.get("correlationId") != correlation_id
            or verified.get("status") != "Pending"
        ):
            raise FieldForceExecutionError("Field Force task readback did not match the requested task")

        return {
            "task_id": task_id,
            "status": verified["status"],
            "assigned_to": verified["assignedTo"],
            "title": verified["title"],
            "correlation_id": correlation_id,
            "verified": True,
            "external_notification_sent": bool(created.get("externalNotificationSent", False)),
        }


def get_field_force_client() -> FieldForceClient:
    return FieldForceClient(
        base_url=os.environ.get("FIELD_FORCE_BASE_URL", ""),
        service_token=os.environ.get("FIELD_FORCE_SERVICE_TOKEN", ""),
    )