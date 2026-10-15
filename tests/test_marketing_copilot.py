# tests/test_marketing_copilot.py
"""Tests for the Marketing Campaign Suite (execute_marketing_campaign)."""

import pytest

from app.services.marketing import MarketingConflict, execute_marketing_campaign


def test_execute_marketing_campaign_success(db_session):
    """Happy‑path: a new campaign is created and returns expected keys."""
    result = execute_marketing_campaign(
        db=db_session,
        campaign_type="social_media",
        target_audience="young_adults",
        idempotency_key="marketing-key-001",
        correlation_id="corr-101",
        agent_id="agent-marketing",
    )
    assert isinstance(result, dict)
    assert result["status"] == "PENDING_APPROVAL"
    assert "campaign_id" in result
    assert "approval_id" in result


def test_execute_marketing_idempotency(db_session):
    """Calling with the same idempotency_key returns the original payload."""
    payload = execute_marketing_campaign(
        db=db_session,
        campaign_type="email",
        target_audience="subscribers",
        idempotency_key="marketing-key-dup",
        correlation_id="corr-202",
        agent_id="agent-marketing",
    )
    # Second call should return the same payload without error
    payload2 = execute_marketing_campaign(
        db=db_session,
        campaign_type="email",
        target_audience="subscribers",
        idempotency_key="marketing-key-dup",
        correlation_id="corr-202",
        agent_id="agent-marketing",
    )
    assert payload2 == payload

def test_execute_marketing_idempotency_conflict(db_session):
    """Reusing an idempotency_key with different payload raises conflict."""
    execute_marketing_campaign(
        db=db_session,
        campaign_type="seo",
        target_audience="tech",
        idempotency_key="conflict-key",
        correlation_id="corr-303",
        agent_id="agent-marketing",
    )
    with pytest.raises(MarketingConflict):
        execute_marketing_campaign(
            db=db_session,
            campaign_type="ads",
            target_audience="tech",
            idempotency_key="conflict-key",
            correlation_id="corr-303",
            agent_id="agent-marketing",
        )
