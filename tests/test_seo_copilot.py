# tests/test_seo_copilot.py

"""Test the SEO Blog Copilot service (execute_seo_draft)."""

import uuid

from app.services.seo import execute_seo_draft


def test_execute_seo_draft_success(httpx_mock, db_session):
    """Happy‑path: a new draft is created and returns the expected keys."""
    # Arrange – deterministic IDs via monkeypatching uuid4
    fixed_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    # Patch uuid.uuid4 to return a constant value
    class DummyUUID:
        @staticmethod
        def uuid4():
            return fixed_uuid
    # Replace in the module namespace
    orig_uuid4 = execute_seo_draft.__globals__["uuid"].uuid4
    execute_seo_draft.__globals__["uuid"].uuid4 = DummyUUID.uuid4

    # Act
    result = execute_seo_draft(
        db=db_session,
        target_network="example.com",
        keywords=["seo", "blog"],
        idempotency_key="test-key",
        correlation_id="corr-001",
        agent_id="agent-xyz",
    )

    # Cleanup
    execute_seo_draft.__globals__["uuid"].uuid4 = orig_uuid4

    # Assert
    assert isinstance(result, dict)
    assert result["status"] == "PENDING_APPROVAL"
    assert "draft_id" in result
    assert "approval_id" in result

    # The mock httpx client is never called directly here – the test focuses on DB flow.
