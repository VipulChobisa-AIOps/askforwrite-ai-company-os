import asyncio
import unittest

import httpx

from app.clients.field_force import (
    FieldForceClient,
    FieldForceExecutionError,
    FieldForceNotConfigured,
)


class FieldForceClientTests(unittest.TestCase):
    def test_posts_authenticated_task_and_verifies_readback(self):
        received = []

        def handler(request: httpx.Request) -> httpx.Response:
            received.append(request)
            if request.method == "POST":
                return httpx.Response(201, json={
                    "taskId": "ff-task-1",
                    "status": "Pending",
                    "assignedTo": "employee-1",
                    "correlationId": "correlation-1",
                    "externalNotificationSent": False,
                })
            return httpx.Response(200, json={
                "taskId": "ff-task-1",
                "title": "Proposal title",
                "assignedTo": "employee-1",
                "status": "Pending",
                "correlationId": "correlation-1",
            })

        client = FieldForceClient(
            "http://field-force.test",
            "field-force-token-for-test-which-is-long-enough",
            transport=httpx.MockTransport(handler),
        )
        result = asyncio.run(client.create_and_verify_task(
            title="Proposal title",
            description="Approved proposal summary",
            assigned_to="employee-1",
            due_date="2026-10-01T10:00:00+00:00",
            idempotency_key="delivery-1",
            correlation_id="correlation-1",
        ))

        self.assertTrue(result["verified"])
        self.assertEqual(result["task_id"], "ff-task-1")
        self.assertEqual(len(received), 2)
        self.assertEqual(received[0].headers["authorization"], "Bearer field-force-token-for-test-which-is-long-enough")
        self.assertEqual(received[0].headers["idempotency-key"], "delivery-1")
        self.assertEqual(received[1].url.path, "/api/agent/tasks/ff-task-1")

    def test_rejects_success_response_without_matching_status_evidence(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(201, json={"taskId": "ff-task-2"})
            return httpx.Response(200, json={
                "taskId": "ff-task-2",
                "title": "Different title",
                "assignedTo": "employee-1",
                "status": "Pending",
                "correlationId": "correlation-2",
            })

        client = FieldForceClient(
            "http://field-force.test",
            "field-force-token-for-test-which-is-long-enough",
            transport=httpx.MockTransport(handler),
        )
        with self.assertRaises(FieldForceExecutionError):
            asyncio.run(client.create_and_verify_task(
                title="Expected title",
                description=None,
                assigned_to="employee-1",
                due_date=None,
                idempotency_key="delivery-2",
                correlation_id="correlation-2",
            ))

    def test_requires_configured_service_token(self):
        client = FieldForceClient("http://field-force.test", "too-short")
        with self.assertRaises(FieldForceNotConfigured):
            asyncio.run(client.create_and_verify_task(
                title="Task",
                description=None,
                assigned_to="employee-1",
                due_date=None,
                idempotency_key="delivery-3",
                correlation_id="correlation-3",
            ))


if __name__ == "__main__":
    unittest.main()