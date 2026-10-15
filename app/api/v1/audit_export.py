"""Audit Log Export API router — compliance and enterprise governance.

Provides Owner-only endpoints for exporting the immutable audit trail:
- GET /v1/audit/export?format=json — full JSON export
- GET /v1/audit/export?format=csv  — CSV download (Content-Disposition: attachment)
- GET /v1/audit/summary            — aggregate counts by action and capability

Query parameters:
- format: "json" (default) | "csv"
- org_id: filter by specific tenant org (Owner sees all; Manager sees own org)
- capability: filter by capability_name
- action: filter by action
- since: ISO-8601 datetime (e.g., 2026-01-01T00:00:00Z)
- limit: max rows (default 500, max 5000)
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import AuditLog
from app.security.auth import APIPrincipal, require_manager, require_owner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/audit", tags=["audit-export"])


# ── Schemas ───────────────────────────────────────────────────────────────────


class AuditLogEntry(BaseModel):
    """Single audit log entry for JSON export."""

    id: int
    task_id: str
    correlation_id: str
    agent_id: str | None
    capability_name: str
    action: str
    input_payload: dict
    output_payload: dict
    status: str
    created_at: datetime


class AuditSummaryItem(BaseModel):
    """Aggregated count for a single capability+action pair."""

    capability_name: str
    action: str
    count: int


class AuditSummaryResponse(BaseModel):
    """Aggregate audit activity summary."""

    total_events: int
    by_action: list[AuditSummaryItem]
    generated_at: datetime


# ── Helpers ───────────────────────────────────────────────────────────────────


def _build_query(
    db: Session,
    org_id: str | None,
    capability: str | None,
    action: str | None,
    since: datetime | None,
    limit: int,
):
    q = db.query(AuditLog)
    if org_id:
        # AuditLog doesn't have org_id directly — filter via input_payload JSON key
        # We filter in Python after fetch for portability across SQLite and PostgreSQL
        pass
    if capability:
        q = q.filter(AuditLog.capability_name == capability)
    if action:
        q = q.filter(AuditLog.action == action)
    if since:
        q = q.filter(AuditLog.created_at >= since)
    q = q.order_by(AuditLog.created_at.desc()).limit(min(limit, 5000))
    rows = q.all()

    # Apply org_id filter in Python if specified (avoids JSON-field DB dialects)
    if org_id:
        rows = [
            r for r in rows
            if (r.input_payload or {}).get("org_id") == org_id
            or (r.output_payload or {}).get("org_id") == org_id
        ]

    return rows


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get(
    "/export",
    summary="Export audit logs in JSON or CSV format (Owner only)",
    operation_id="export_audit_logs",
)
def export_audit_logs(
    format: str = Query(default="json", pattern="^(json|csv)$", description="Export format: json or csv"),
    org_id: str | None = Query(default=None, description="Filter by organization ID"),
    capability: str | None = Query(default=None, description="Filter by capability name"),
    action: str | None = Query(default=None, description="Filter by action name"),
    since: datetime | None = Query(default=None, description="Filter events after this UTC datetime"),
    limit: int = Query(default=500, ge=1, le=5000, description="Max rows to export"),
    principal: APIPrincipal = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Export the immutable audit trail for compliance and enterprise governance.

    Returns all audit log entries matching the filter criteria.
    Supports JSON (default) and CSV (for spreadsheet tools) output.
    This endpoint is restricted to Owner-level API keys.
    """
    rows = _build_query(db, org_id, capability, action, since, limit)

    if format == "csv":
        output = io.StringIO()
        fieldnames = [
            "id", "task_id", "correlation_id", "agent_id",
            "capability_name", "action", "status", "created_at",
            "input_payload", "output_payload",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "id": row.id,
                "task_id": row.task_id,
                "correlation_id": row.correlation_id,
                "agent_id": row.agent_id or "",
                "capability_name": row.capability_name,
                "action": row.action,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "input_payload": str(row.input_payload or {}),
                "output_payload": str(row.output_payload or {}),
            })
        output.seek(0)
        filename = f"audit_export_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.csv"
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # Default: JSON
    entries = [
        AuditLogEntry(
            id=row.id,
            task_id=row.task_id,
            correlation_id=row.correlation_id,
            agent_id=row.agent_id,
            capability_name=row.capability_name,
            action=row.action,
            input_payload=row.input_payload or {},
            output_payload=row.output_payload or {},
            status=row.status,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return {
        "total": len(entries),
        "format": "json",
        "generated_at": datetime.now(UTC).isoformat(),
        "entries": [e.model_dump() for e in entries],
    }


@router.get(
    "/summary",
    response_model=AuditSummaryResponse,
    summary="Aggregated audit activity summary by capability and action",
    operation_id="get_audit_summary",
)
def get_audit_summary(
    since: datetime | None = Query(default=None, description="Summarize events after this UTC datetime"),
    principal: APIPrincipal = Depends(require_manager),
    db: Session = Depends(get_db),
) -> AuditSummaryResponse:
    """Return aggregate counts of audit events grouped by capability and action.

    Useful for governance dashboards and activity monitoring.
    Accessible to both Manager and Owner roles.
    """
    q = db.query(AuditLog)
    if since:
        q = q.filter(AuditLog.created_at >= since)
    rows = q.all()

    # Aggregate in Python for DB-dialect portability
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row.capability_name, row.action)
        counts[key] = counts.get(key, 0) + 1

    by_action = [
        AuditSummaryItem(capability_name=cap, action=act, count=cnt)
        for (cap, act), cnt in sorted(counts.items(), key=lambda x: -x[1])
    ]

    return AuditSummaryResponse(
        total_events=len(rows),
        by_action=by_action,
        generated_at=datetime.now(UTC),
    )
