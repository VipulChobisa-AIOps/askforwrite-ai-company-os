import asyncio
from uuid import uuid4

import pytest

from app.db.models import (
    ApprovalRequest,
    DeliveryRecord,
    LeadRecordRow,
    ProposalRecord,
    TaskRecord,
)
from app.services.approvals import request_approval
from app.services.delivery import (
    DeliveryNotApproved,
    execute_delivery,
)


# Simple mock FieldForceClient
class MockFieldForceClient:
    async def create_and_verify_task(self, *, title, description, assigned_to, due_date, idempotency_key, correlation_id):
        return {"task_id": "ff-123", "verified": True}

@pytest.fixture
def task(db_session):
    t = TaskRecord(id=str(uuid4()), objective="Test Task")
    db_session.add(t)
    db_session.commit()
    return t

@pytest.fixture
def lead(db_session, task):
    l = LeadRecordRow(
        id=str(uuid4()),
        task_id=task.id,
        company="Acme Corp",
        website="https://acme.example.com",
        industry="Manufacturing",
        geography="US",
        do_not_contact=False,
        status="PROPOSAL_APPROVED",
    )
    db_session.add(l)
    db_session.commit()
    return l

@pytest.fixture
def approved_proposal(db_session, task, lead):
    # Create approval request and approve it
    approval = request_approval(
        db=db_session,
        task_id=task.id,
        lead_id=lead.id,
        action="proposal_delivery",
        detail={},
        idempotency_key="approval-key",
        requested_by="owner",
        correlation_id="corr-1",
        proposal_id=None,
    )
    # Manually set to approved (bypass decide_approval for brevity)
    appr = db_session.get(ApprovalRequest, approval["approval_id"])
    appr.status = "APPROVED"
    appr.decided_by = "owner"
    db_session.commit()
    # Create proposal linked to this approval
    prop = ProposalRecord(
        id=str(uuid4()),
        task_id=task.id,
        lead_id=lead.id,
        approval_id=appr.id,
        title="Test Proposal",
        summary="Test summary",
        status="APPROVED",
    )
    db_session.add(prop)
    db_session.commit()
    return prop

def test_execute_delivery_success(db_session, task, lead, approved_proposal):
    result = asyncio.run(
        execute_delivery(
            db=db_session,
            proposal_id=approved_proposal.id,
            assigned_to="employee-1",
            due_date=None,
            idempotency_key="delivery-key",
            correlation_id="corr-2",
            manager_id="owner",
            client=MockFieldForceClient(),
        )
    )
    assert result["status"] == "COMPLETED"
    assert result["proposal_id"] == approved_proposal.id
    # Verify delivery record created
    delivery = db_session.query(DeliveryRecord).filter_by(proposal_id=approved_proposal.id).first()
    assert delivery is not None
    assert delivery.status == "DELIVERED"

def test_execute_delivery_not_approved(db_session, task, lead):
    # Create a proposal without approval
    prop = ProposalRecord(
        id=str(uuid4()),
        task_id=task.id,
        lead_id=lead.id,
        title="Unapproved",
        summary="",
        status="DRAFT",
    )
    db_session.add(prop)
    db_session.commit()
    with pytest.raises(DeliveryNotApproved):
        asyncio.run(
            execute_delivery(
                db=db_session,
                proposal_id=prop.id,
                assigned_to="employee-1",
                due_date=None,
                idempotency_key="delivery-key-2",
                correlation_id="corr-3",
                manager_id="owner",
                client=MockFieldForceClient(),
            )
        )
