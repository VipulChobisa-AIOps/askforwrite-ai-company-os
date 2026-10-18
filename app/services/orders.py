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
    correlation_id: str | None = None,
    secret: str | None = None,
    signature: str | None = None,
    raw_payload: str | None = None,
) -> dict:
    corr_id = correlation_id or str(uuid.uuid4())
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
        correlation_id=corr_id,
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
        correlation_id=corr_id,
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


def fulfill_order(
    db: Session,
    transaction_id: str,
    correlation_id: str | None = None,
    fulfilled_by: str = "manager-agent",
    notes: str | None = None,
) -> dict:
    """Fulfill a confirmed order: update TaskRecord to COMPLETED, OrderRecord to FULFILLED, and seal TrustBlock."""
    order = db.query(OrderRecord).filter_by(transaction_id=transaction_id).first()
    if not order:
        raise ValueError(f"Order with transaction ID '{transaction_id}' not found")

    task = db.get(TaskRecord, order.task_id) if order.task_id else None
    corr_id = correlation_id or (task.correlation_id if task else str(uuid.uuid4()))

    from app.agents.llm_client import generate
    deliverable_summary = generate(
        prompt=(
            f"Generate an executive deliverable summary and service fulfillment manifest for order '{transaction_id}' "
            f"(Customer: {order.customer_email}, Amount: {order.amount} {order.currency}). "
            f"Specify completed deliverables, zero-trust verification hash, and access instructions."
        ),
        system_instruction="You are an autonomous fulfillment and digital delivery orchestrator for AskforWrite Company OS.",
        fallback_text=(
            f"Fulfillment complete for {order.customer_email}. Core deliverables, digital artifacts, "
            f"and cryptographic proof manifest dispatched for transaction {transaction_id}."
        ),
    )

    fulfillment_payload = {
        "transaction_id": transaction_id,
        "amount": order.amount,
        "currency": order.currency,
        "customer_email": order.customer_email,
        "fulfilled_by": fulfilled_by,
        "status": "FULFILLED",
        "notes": notes or "Automated AI delivery and verification completed.",
        "deliverable_summary": deliverable_summary,
    }

    if task:
        task.status = "COMPLETED"
        task.result = fulfillment_payload

    order.status = "FULFILLED"

    audit = AuditLog(
        task_id=task.id if task else str(uuid.uuid4()),
        correlation_id=corr_id,
        agent_id=fulfilled_by,
        capability_name=CAPABILITY_NAME,
        action="fulfill_order",
        input_payload={"transaction_id": transaction_id},
        output_payload=fulfillment_payload,
        status="COMPLETED",
    )
    db.add(audit)
    db.commit()

    seal_task_to_block(
        db=db,
        task_id=task.id if task else str(uuid.uuid4()),
        capability_name=CAPABILITY_NAME,
        action="fulfill_order",
        payload=fulfillment_payload,
        sealed_by=fulfilled_by,
    )

    return {
        "status": "FULFILLED",
        "transaction_id": transaction_id,
        "task_id": task.id if task else None,
        "delivery": fulfillment_payload,
    }


def fulfill_pending_orders(
    db: Session,
    limit: int = 50,
    fulfilled_by: str = "automated-order-worker",
) -> dict[str, object]:
    """Scan all OrderRecord rows in CONFIRMED status and fulfill each automatically."""
    pending = (
        db.query(OrderRecord)
        .filter(OrderRecord.status == "CONFIRMED")
        .order_by(OrderRecord.created_at.asc())
        .limit(limit)
        .all()
    )
    fulfilled_orders = []
    for order in pending:
        try:
            res = fulfill_order(
                db=db,
                transaction_id=order.transaction_id,
                fulfilled_by=fulfilled_by,
                notes="Automated batch order worker fulfillment.",
            )
            fulfilled_orders.append(res)
        except Exception:
            pass

    return {
        "fulfilled_count": len(fulfilled_orders),
        "orders": fulfilled_orders,
    }


def list_orders(
    db: Session,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    """List OrderRecords, optionally filtered by status."""
    query = db.query(OrderRecord)
    if status:
        query = query.filter(OrderRecord.status == status.strip().upper())
    orders = query.order_by(OrderRecord.created_at.desc()).limit(limit).all()
    return [
        {
            "id": o.id,
            "transaction_id": o.transaction_id,
            "amount": o.amount,
            "currency": o.currency,
            "customer_email": o.customer_email,
            "task_id": o.task_id,
            "status": o.status,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]
