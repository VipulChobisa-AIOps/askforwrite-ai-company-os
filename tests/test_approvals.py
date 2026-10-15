from uuid import uuid4

import pytest

from app.db.models import LeadRecordRow, TaskRecord
from app.services.approvals import (
    ApprovalConflict,
    decide_approval,
    request_approval,
)


@pytest.fixture
def task(db_session):
    task = TaskRecord(id=str(uuid4()), objective="Test Task")
    db_session.add(task)
    db_session.commit()
    return task

@pytest.fixture
def lead(db_session, task):
    lead = LeadRecordRow(
        id=str(uuid4()),
        task_id=task.id,
        company="Acme Corp",
        website="https://acme.example.com",
        industry="Manufacturing",
        geography="US",
        do_not_contact=False,
        status="DISCOVERED",
    )
    db_session.add(lead)
    db_session.commit()
    return lead

def test_request_approval_idempotent(db_session, task, lead):
    payload = {"foo": "bar"}
    result1 = request_approval(
        db=db_session,
        task_id=task.id,
        lead_id=lead.id,
        action="external_sales_outreach",
        detail=payload,
        idempotency_key="key-123",
        requested_by="owner",
        correlation_id="corr-1",
    )
    assert result1["status"] == "PENDING"
    result2 = request_approval(
        db=db_session,
        task_id=task.id,
        lead_id=lead.id,
        action="external_sales_outreach",
        detail=payload,
        idempotency_key="key-123",
        requested_by="owner",
        correlation_id="corr-1",
    )
    assert result1["approval_id"] == result2["approval_id"]

def test_request_approval_conflict(db_session, task, lead):
    payload1 = {"foo": "bar"}
    payload2 = {"foo": "baz"}
    request_approval(
        db=db_session,
        task_id=task.id,
        lead_id=lead.id,
        action="external_sales_outreach",
        detail=payload1,
        idempotency_key="conflict-key",
        requested_by="owner",
        correlation_id="corr-1",
    )
    with pytest.raises(ApprovalConflict):
        request_approval(
            db=db_session,
            task_id=task.id,
            lead_id=lead.id,
            action="external_sales_outreach",
            detail=payload2,
            idempotency_key="conflict-key",
            requested_by="owner",
            correlation_id="corr-2",
        )

def test_decide_approval_success(db_session, task, lead):
    payload = {"info": 42}
    approval = request_approval(
        db=db_session,
        task_id=task.id,
        lead_id=lead.id,
        action="external_sales_outreach",
        detail=payload,
        idempotency_key="decide-key",
        requested_by="owner",
        correlation_id="corr-3",
    )
    result = decide_approval(
        db=db_session,
        approval_id=approval["approval_id"],
        decision="APPROVED",
        decided_by="owner",
        correlation_id="corr-3",
    )
    assert result["status"] == "APPROVED"
    refreshed_lead = db_session.get(LeadRecordRow, lead.id)
    assert refreshed_lead.status == "APPROVED_FOR_OUTREACH"

def test_decide_approval_invalid_state(db_session, task, lead):
    payload = {"info": 99}
    approval = request_approval(
        db=db_session,
        task_id=task.id,
        lead_id=lead.id,
        action="external_sales_outreach",
        detail=payload,
        idempotency_key="invalid-key",
        requested_by="owner",
        correlation_id="corr-4",
    )
    decide_approval(
        db=db_session,
        approval_id=approval["approval_id"],
        decision="APPROVED",
        decided_by="owner",
        correlation_id="corr-4",
    )
    with pytest.raises(ApprovalConflict):
        decide_approval(
            db=db_session,
            approval_id=approval["approval_id"],
            decision="REJECTED",
            decided_by="owner",
            correlation_id="corr-5",
        )
