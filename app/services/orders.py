"""Inbound order ingestion and task routing (ASK4)."""

import hashlib
import hmac
import json
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import AuditLog, IdempotencyRecord, OrderRecord, TaskRecord
from app.security.trust_chain import seal_task_to_block

CAPABILITY_NAME = "askforwrite_academic_ask4"


class OrderConflict(Exception):
    """Raised when an order fails uniqueness or idempotency constraints."""


class OrderValidationFailed(Exception):
    """Raised when an order fails signature validation."""


def verify_order_signature(payload_str: str, signature: str, secret: str) -> bool:
    if not secret:
        return False
    expected = hmac.new(secret.encode(), payload_str.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def ingest_order(
    db: Session,
    transaction_id: str,
    amount: float,
    currency: str,
    customer_email: str,
    idempotency_key: str,
    correlation_id: str,
    secret: str | None = None,
    signature: str | None = None,
    raw_payload: str | None = None,
) -> dict:
    if secret and signature and raw_payload:
        if not verify_order_signature(raw_payload, signature, secret):
            raise OrderValidationFailed("Invalid signature")

    request_hash = hashlib.sha256(json.dumps({"transaction_id": transaction_id}, sort_keys=True).encode()).hexdigest()

    existing_idempotency = db.query(IdempotencyRecord).filter_by(
        capability_name=CAPABILITY_NAME,
        idempotency_key=idempotency_key,
    ).first()

    if existing_idempotency:
        if existing_idempotency.request_hash != request_hash:
            raise OrderConflict("Idempotency key reused with different request payload")
        return existing_idempotency.response_payload

    # Create task for the Manager agent to orchestrate fulfillment
    task_id = str(uuid.uuid4())
    task = TaskRecord(
        id=task_id,
        correlation_id=correlation_id,
        objective=f"Fulfill ASK4 Order {transaction_id}",
        status="PENDING",
    )
    db.add(task)

    order = OrderRecord(
        transaction_id=transaction_id,
        amount=amount,
        currency=currency,
        customer_email=customer_email,
        task_id=task_id,
        status="CONFIRMED"
    )
    db.add(order)

    audit = AuditLog(
        task_id=task_id,
        correlation_id=correlation_id,
        agent_id="webhook",
        capability_name=CAPABILITY_NAME,
        action="ingest_order",
        input_payload={"transaction_id": transaction_id, "amount": amount, "currency": currency},
        output_payload={"status": "CONFIRMED", "task_id": task_id},
        status="COMPLETED"
    )
    db.add(audit)

    result = {
        "status": "CONFIRMED",
        "task_id": task_id,
        "transaction_id": transaction_id
    }

    idempotency = IdempotencyRecord(
        capability_name=CAPABILITY_NAME,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        task_id=task_id,
        response_payload=result,
    )
    db.add(idempotency)
    
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise OrderConflict("Transaction ID already exists or idempotency conflict") from exc

    seal_task_to_block(
        db=db,
        task_id=task_id,
        capability_name=CAPABILITY_NAME,
        action="ingest_order",
        payload=result,
        sealed_by="webhook",
    )

    return result
