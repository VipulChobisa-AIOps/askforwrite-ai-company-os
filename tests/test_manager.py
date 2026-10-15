from uuid import uuid4

import pytest

from app.db.models import TaskRecord
from app.services.manager import execute_manager_workflow


@pytest.fixture
def task(db_session):
    t = TaskRecord(id=str(uuid4()), objective="Test Manager Task")
    db_session.add(t)
    db_session.commit()
    return t

def test_manager_workflow_creates_task_and_returns_response(db_session, task):
    result = execute_manager_workflow(
        db=db_session,
        objective="Find field force prospects",
        limit=2,
        idempotency_key="mgr-key-1",
        correlation_id="corr-1",
        manager_id="owner",
    )
    assert "task_id" in result
    assert result["status"] in {"HUMAN_APPROVAL_REQUIRED", "COMPLETED"}
    # Verify task persisted
    stored = db_session.get(TaskRecord, result["task_id"])
    assert stored is not None
    assert stored.objective == "Find field force prospects"

def test_manager_workflow_idempotent_returns_same_result(db_session, task):
    first = execute_manager_workflow(
        db=db_session,
        objective="Find field force prospects",
        limit=2,
        idempotency_key="mgr-key-idem",
        correlation_id="corr-2",
        manager_id="owner",
    )
    second = execute_manager_workflow(
        db=db_session,
        objective="Find field force prospects",
        limit=2,
        idempotency_key="mgr-key-idem",
        correlation_id="corr-2",
        manager_id="owner",
    )
    assert first["task_id"] == second["task_id"]
    assert first == second
