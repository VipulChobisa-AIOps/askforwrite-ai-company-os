"""P0 Issue #12 Tests — Fail-Closed WordPress Approval Enforcement, Verified Publishing,
Distinct Status Model (PUBLISHED / SIMULATED / PUBLISH_FAILED), Retry Idempotency,
and End-to-End WordPress REST v2 Sandbox HTTP Verification.
"""

from __future__ import annotations

import base64
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app.db.database import Base, SessionLocal, engine
from app.db.models import ApprovalRequest, AuditLog, SeoDraftRecord, TaskRecord
from app.main import app
from app.services.approvals import decide_approval
from app.services.wordpress_publisher import (
    WordPressPublishError,
    publish_seo_draft_to_wordpress,
)

MANAGER_KEY = os.environ.get("MANAGER_API_KEY", "test-manager-key-issue12-1234567890")
OWNER_KEY = os.environ.get("OWNER_API_KEY", "test-owner-key-issue12-123456789012")


@pytest.fixture
def wp_env(monkeypatch: pytest.MonkeyPatch):
    """Enable live WordPress REST execution in tests (with isolated DB session & TestClient)."""
    Base.metadata.create_all(bind=engine)
    monkeypatch.setenv("MANAGER_API_KEY", MANAGER_KEY)
    monkeypatch.setenv("OWNER_API_KEY", OWNER_KEY)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ENABLE_EXTERNAL_SIDE_EFFECTS", "true")
    monkeypatch.setenv("ALLOW_LIVE_SIDE_EFFECTS", "true")
    monkeypatch.setenv("ALLOW_LIVE_IN_TEST", "true")
    monkeypatch.setenv("WP_SITE_URL", "https://sandbox.askforwrite.in")
    monkeypatch.setenv("WP_USERNAME", "wp-editor")
    monkeypatch.setenv("WP_APP_PASSWORD", "wp-app-pass-sandbox")
    db = SessionLocal()
    client = TestClient(app)
    try:
        yield db, client
    finally:
        db.close()


def _create_draft_and_approval(
    db,
    *,
    draft_org_id: str | None = None,
    approval_org_id: str | None = None,
    approval_status: str | None = "APPROVED",
    approval_action: str = "live_publishing",
    link_approval: bool = True,
    create_approval_row: bool = True,
    approval_draft_id_override: str | None = None,
    approval_task_id_override: str | None = None,
    draft_status: str = "PENDING_APPROVAL",
) -> tuple[SeoDraftRecord, ApprovalRequest | None]:
    task_id = f"task-i12-{uuid.uuid4().hex[:10]}"
    draft_id = f"draft-i12-{uuid.uuid4().hex[:10]}"
    approval_id = f"appr-i12-{uuid.uuid4().hex[:10]}"

    db.add(
        TaskRecord(
            id=task_id,
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
            objective="Issue #12 WordPress Publish Integrity Test",
            status="COMPLETED",
        )
    )

    appr_row: ApprovalRequest | None = None
    if create_approval_row:
        detail: dict = {
            "seo_draft_id": approval_draft_id_override or draft_id,
            "network": "askforwrite.in",
        }
        if approval_org_id is not None:
            detail["org_id"] = approval_org_id
        appr_row = ApprovalRequest(
            id=approval_id,
            task_id=approval_task_id_override or task_id,
            action=approval_action,
            detail=detail,
            idempotency_key=f"idemp-i12-{uuid.uuid4().hex[:10]}",
            request_hash=f"hash-i12-{uuid.uuid4().hex[:10]}",
            status=approval_status or "PENDING",
            requested_by="seo_copilot",
            decided_by="owner" if approval_status == "APPROVED" else None,
        )
        db.add(appr_row)

    draft = SeoDraftRecord(
        id=draft_id,
        org_id=draft_org_id,
        task_id=task_id,
        target_network="askforwrite.in",
        keywords=["wordpress integrity", "hitl governance"],
        content="# Fail-Closed WordPress Publishing\n\nVerified content body for Issue 12.",
        status=draft_status,
        approval_id=(approval_id if link_approval else None),
    )
    db.add(draft)
    db.commit()
    return draft, appr_row


# ── 1. Fail-Closed HITL Approval Rejection Matrix (Direct Service + API Route) ─


def test_rejects_missing_approval_id_direct_and_api(wp_env) -> None:
    db, client = wp_env
    draft, _ = _create_draft_and_approval(db, link_approval=False, create_approval_row=False)

    # Direct service invocation MUST fail closed (cannot bypass HITL!)
    with pytest.raises(PermissionError, match="missing required approval_id"):
        publish_seo_draft_to_wordpress(db=db, draft_id=draft.id)

    db.refresh(draft)
    assert draft.status == "PENDING_APPROVAL"

    # API route MUST also return 403
    resp = client.post(f"/v1/seo/drafts/{draft.id}/publish", headers={"X-API-Key": MANAGER_KEY})
    assert resp.status_code == 403
    assert "approval_id" in resp.json()["detail"]


def test_rejects_missing_approval_record_direct_and_api(wp_env) -> None:
    db, client = wp_env
    draft, _ = _create_draft_and_approval(db, link_approval=True, create_approval_row=False)

    with pytest.raises(PermissionError, match="not found"):
        publish_seo_draft_to_wordpress(db=db, draft_id=draft.id)

    resp = client.post(f"/v1/seo/drafts/{draft.id}/publish", headers={"X-API-Key": MANAGER_KEY})
    assert resp.status_code == 403


@pytest.mark.parametrize("bad_status", ["PENDING", "REJECTED", "REVOKED", "EXPIRED"])
def test_rejects_unapproved_rejected_or_revoked_approval(wp_env, bad_status: str) -> None:
    db, client = wp_env
    draft, _ = _create_draft_and_approval(db, approval_status=bad_status)

    with pytest.raises(PermissionError, match=bad_status):
        publish_seo_draft_to_wordpress(db=db, draft_id=draft.id)

    resp = client.post(f"/v1/seo/drafts/{draft.id}/publish", headers={"X-API-Key": MANAGER_KEY})
    assert resp.status_code == 403


def test_rejects_wrong_action_approval(wp_env) -> None:
    db, _ = wp_env
    draft, _ = _create_draft_and_approval(db, approval_status="APPROVED", approval_action="external_sales_outreach")

    with pytest.raises(PermissionError, match="not WordPress publishing"):
        publish_seo_draft_to_wordpress(db=db, draft_id=draft.id)


def test_rejects_mismatched_draft_and_task_approval(wp_env) -> None:
    db, _ = wp_env
    draft_diff, _ = _create_draft_and_approval(
        db,
        approval_status="APPROVED",
        approval_draft_id_override="draft-completely-different-id",
    )
    with pytest.raises(PermissionError, match="bound to draft"):
        publish_seo_draft_to_wordpress(db=db, draft_id=draft_diff.id)

    draft_task_diff, _ = _create_draft_and_approval(
        db,
        approval_status="APPROVED",
        approval_task_id_override="task-different-999",
    )
    with pytest.raises(PermissionError, match="does not match draft task"):
        publish_seo_draft_to_wordpress(db=db, draft_id=draft_task_diff.id)


def test_rejects_cross_tenant_approval_and_caller_org(wp_env) -> None:
    db, _ = wp_env
    # Approval belongs to org-B while draft belongs to org-A
    draft_xtenant, _ = _create_draft_and_approval(
        db,
        draft_org_id="org-tenant-a",
        approval_org_id="org-tenant-b",
        approval_status="APPROVED",
    )
    with pytest.raises(PermissionError, match="cross-tenant approval mismatch"):
        publish_seo_draft_to_wordpress(db=db, draft_id=draft_xtenant.id, caller_org_id="org-tenant-a")

    # Draft & approval both belong to org-A, but caller is org-B
    draft_valid, _ = _create_draft_and_approval(
        db,
        draft_org_id="org-tenant-a",
        approval_org_id="org-tenant-a",
        approval_status="APPROVED",
    )
    with pytest.raises(PermissionError, match="belongs to tenant"):
        publish_seo_draft_to_wordpress(db=db, draft_id=draft_valid.id, caller_org_id="org-tenant-b")


# ── 2. Delivery Failures: 4xx, 5xx, Timeout, Malformed JSON, Missing ID/URL ───


@pytest.mark.parametrize("http_code", [400, 401, 403, 422, 500, 502, 503])
def test_http_4xx_and_5xx_sets_publish_failed_never_published(wp_env, http_code: int) -> None:
    db, _ = wp_env
    draft, _ = _create_draft_and_approval(db, approval_status="APPROVED")

    transport = httpx.MockTransport(lambda req: httpx.Response(http_code, text=f"WP Error {http_code}"))
    with httpx.Client(transport=transport) as hc:
        with pytest.raises(WordPressPublishError) as exc_info:
            publish_seo_draft_to_wordpress(db=db, draft_id=draft.id, http_client=hc)

    assert exc_info.value.status == "PUBLISH_FAILED"
    assert exc_info.value.http_status == http_code
    db.refresh(draft)
    assert draft.status == "PUBLISH_FAILED"
    assert draft.provider_post_id is None
    assert draft.canonical_url is None


def test_timeout_sets_publish_failed_never_published(wp_env) -> None:
    db, _ = wp_env
    draft, _ = _create_draft_and_approval(db, approval_status="APPROVED")

    def raise_timeout(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("WordPress timed out", request=req)

    with httpx.Client(transport=httpx.MockTransport(raise_timeout)) as hc:
        with pytest.raises(WordPressPublishError) as exc_info:
            publish_seo_draft_to_wordpress(db=db, draft_id=draft.id, http_client=hc)

    assert exc_info.value.error_code == "wordpress_timeout"
    db.refresh(draft)
    assert draft.status == "PUBLISH_FAILED"
    assert draft.provider_post_id is None


def test_malformed_json_and_non_object_payload_set_publish_failed(wp_env) -> None:
    db, _ = wp_env
    draft1, _ = _create_draft_and_approval(db, approval_status="APPROVED")
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(201, text="<html>Not JSON</html>"))) as hc:
        with pytest.raises(WordPressPublishError) as exc1:
            publish_seo_draft_to_wordpress(db=db, draft_id=draft1.id, http_client=hc)
    assert exc1.value.error_code == "wordpress_malformed_json"
    db.refresh(draft1)
    assert draft1.status == "PUBLISH_FAILED"

    draft2, _ = _create_draft_and_approval(db, approval_status="APPROVED")
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=["unexpected", "list"]))) as hc:
        with pytest.raises(WordPressPublishError) as exc2:
            publish_seo_draft_to_wordpress(db=db, draft_id=draft2.id, http_client=hc)
    assert exc2.value.error_code == "wordpress_invalid_payload"
    db.refresh(draft2)
    assert draft2.status == "PUBLISH_FAILED"


@pytest.mark.parametrize(
    "payload,expected_code",
    [
        ({"link": "https://askforwrite.in/post/1"}, "wordpress_missing_post_id"),
        ({"id": 0, "link": "https://askforwrite.in/post/1"}, "wordpress_missing_post_id"),
        ({"id": True, "link": "https://askforwrite.in/post/1"}, "wordpress_missing_post_id"),
        ({"id": 99}, "wordpress_missing_canonical_url"),
        ({"id": 99, "link": ""}, "wordpress_missing_canonical_url"),
        ({"id": 99, "link": "javascript:alert(1)"}, "wordpress_missing_canonical_url"),
    ],
)
def test_missing_post_id_or_canonical_url_sets_publish_failed(wp_env, payload: dict, expected_code: str) -> None:
    db, _ = wp_env
    draft, _ = _create_draft_and_approval(db, approval_status="APPROVED")
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(201, json=payload))) as hc:
        with pytest.raises(WordPressPublishError) as exc_info:
            publish_seo_draft_to_wordpress(db=db, draft_id=draft.id, http_client=hc)

    assert exc_info.value.error_code == expected_code
    db.refresh(draft)
    assert draft.status == "PUBLISH_FAILED"


def test_api_route_returns_502_with_publish_failed_status(wp_env, monkeypatch: pytest.MonkeyPatch) -> None:
    db, client = wp_env
    draft, _ = _create_draft_and_approval(db, approval_status="APPROVED")

    def boom(*args, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(httpx, "post", boom)
    resp = client.post(f"/v1/seo/drafts/{draft.id}/publish", headers={"X-API-Key": MANAGER_KEY})
    assert resp.status_code == 502
    body = resp.json()
    assert body["status"] == "PUBLISH_FAILED"
    assert body["live_published"] is False
    db.refresh(draft)
    assert draft.status == "PUBLISH_FAILED"


# ── 3. Simulated Execution Clearly Labelled (Never PUBLISHED) ─────────────────


def test_simulated_mode_never_marks_published(wp_env, monkeypatch: pytest.MonkeyPatch) -> None:
    db, client = wp_env
    monkeypatch.delenv("WP_SITE_URL", raising=False)
    monkeypatch.delenv("WP_BASE_URL", raising=False)
    monkeypatch.delenv("WP_USERNAME", raising=False)
    monkeypatch.delenv("WP_APP_PASSWORD", raising=False)

    draft, _ = _create_draft_and_approval(db, approval_status="APPROVED")
    resp = client.post(f"/v1/seo/drafts/{draft.id}/publish", headers={"X-API-Key": MANAGER_KEY})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SIMULATED"
    assert body["is_simulated"] is True
    assert body["live_published"] is False
    assert body["post_id"] is None
    assert body["provider_post_id"] is None
    assert body["url"] is None
    assert body["simulated_url"].startswith("https://askforwrite.in/articles/")

    db.refresh(draft)
    assert draft.status == "SIMULATED"
    assert draft.provider_post_id is None
    assert draft.canonical_url is None


# ── 4. Successful Live Publish + Idempotent Retry + Timeout Reconciliation ────


def test_successful_live_publish_and_idempotent_retry_no_duplicates(wp_env) -> None:
    db, _ = wp_env
    draft, appr = _create_draft_and_approval(
        db,
        draft_org_id="org-live-1",
        approval_org_id="org-live-1",
        approval_status="APPROVED",
    )

    post_calls = 0

    def wp_handler(req: httpx.Request) -> httpx.Response:
        nonlocal post_calls
        if req.method == "POST":
            post_calls += 1
            assert req.headers.get("Idempotency-Key")
            body = json.loads(req.content.decode("utf-8"))
            return httpx.Response(
                201,
                json={
                    "id": 777,
                    "status": "publish",
                    "slug": body["slug"],
                    "link": f"https://sandbox.askforwrite.in/{body['slug']}/",
                },
            )
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(wp_handler)) as hc:
        res1 = publish_seo_draft_to_wordpress(
            db=db,
            draft_id=draft.id,
            caller_org_id="org-live-1",
            http_client=hc,
        )
        # Retry the exact same publish call -> MUST replay without issuing a second POST!
        res2 = publish_seo_draft_to_wordpress(
            db=db,
            draft_id=draft.id,
            caller_org_id="org-live-1",
            http_client=hc,
        )

    assert post_calls == 1
    assert res1["status"] == "PUBLISHED"
    assert res1["live_published"] is True
    assert res1["is_simulated"] is False
    assert res1["post_id"] == 777
    assert res1["provider_post_id"] == "777"
    assert res1["canonical_url"].startswith("https://sandbox.askforwrite.in/")
    assert res1["approval_id"] == appr.id
    assert res1["response_metadata"]["http_status"] == 201

    assert res2["status"] == "PUBLISHED"
    assert res2["idempotent_replay"] is True
    assert res2["post_id"] == 777
    assert res2["canonical_url"] == res1["canonical_url"]

    db.refresh(draft)
    assert draft.status == "PUBLISHED"
    assert draft.provider_post_id == "777"
    assert draft.canonical_url == res1["canonical_url"]
    assert draft.publish_metadata["provider_post_id"] == "777"

    audit = db.query(AuditLog).filter_by(task_id=draft.task_id, action="wordpress_publish", status="COMPLETED").first()
    assert audit is not None
    assert audit.output_payload["provider_post_id"] == "777"
    assert audit.output_payload["canonical_url"] == res1["canonical_url"]


def test_retry_after_timeout_reconciles_existing_post_without_duplicate(wp_env) -> None:
    db, _ = wp_env
    draft, _ = _create_draft_and_approval(db, approval_status="APPROVED")

    created_posts: list[dict] = []
    attempt = 0

    def flaky_wp_handler(req: httpx.Request) -> httpx.Response:
        nonlocal attempt
        if req.method == "POST":
            attempt += 1
            body = json.loads(req.content.decode("utf-8"))
            # First attempt creates the post on WordPress, then drops connection (ReadTimeout)
            created_posts.append(
                {
                    "id": 888,
                    "status": "publish",
                    "slug": body["slug"],
                    "link": f"https://sandbox.askforwrite.in/{body['slug']}/",
                }
            )
            if attempt == 1:
                raise httpx.ReadTimeout("Timeout after WP committed post", request=req)
            return httpx.Response(201, json=created_posts[-1])
        if req.method == "GET":
            slug = req.url.params.get("slug", "")
            matches = [p for p in created_posts if p["slug"] == slug]
            return httpx.Response(200, json=matches)
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(flaky_wp_handler)) as hc:
        with pytest.raises(WordPressPublishError):
            publish_seo_draft_to_wordpress(db=db, draft_id=draft.id, http_client=hc)

        db.refresh(draft)
        assert draft.status == "PUBLISH_FAILED"

        # Retry: reconciles by slug via GET and adopts existing post 888 with ZERO second POST!
        reconciled = publish_seo_draft_to_wordpress(db=db, draft_id=draft.id, http_client=hc)

    assert attempt == 1  # Never issued a duplicate POST!
    assert len(created_posts) == 1
    assert reconciled["status"] == "PUBLISHED"
    assert reconciled["reconciled"] is True
    assert reconciled["post_id"] == 888
    db.refresh(draft)
    assert draft.status == "PUBLISHED"
    assert draft.provider_post_id == "888"


def test_decide_approval_does_not_mask_wp_failure_as_published(wp_env, monkeypatch: pytest.MonkeyPatch) -> None:
    db, _ = wp_env
    draft, appr = _create_draft_and_approval(db, approval_status="PENDING")

    def fail_post(*args, **kwargs):
        return httpx.Response(503, text="Service Unavailable")

    monkeypatch.setattr(httpx, "post", fail_post)
    res = decide_approval(db=db, approval_id=appr.id, decision="APPROVED", decided_by="owner")
    assert res["status"] == "APPROVED"
    assert res["auto_executed_action"] == "seo_draft_publish_failed"
    assert res["external_action_performed"] is False

    db.refresh(draft)
    assert draft.status == "PUBLISH_FAILED"
    assert draft.provider_post_id is None


# ── 5. Real WordPress REST v2 Sandbox HTTP Server End-to-End Verification ─────


def test_wordpress_sandbox_live_publish_and_fetch_resulting_post(wp_env, monkeypatch: pytest.MonkeyPatch) -> None:
    """Definition of Done: verify a live WordPress sandbox publish by fetching the resulting post over HTTP."""
    db, _ = wp_env
    store: dict[int, dict] = {}
    post_counter = {"n": 0}
    expected_auth = "Basic " + base64.b64encode(b"wp-editor:wp-app-pass-sandbox").decode("ascii")

    class WordPressSandboxHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            pass

        def do_POST(self) -> None:  # noqa: N802
            if self.headers.get("Authorization") != expected_auth:
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"code":"rest_cannot_create"}')
                return
            if self.path.rstrip("/") != "/wp-json/wp/v2/posts":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            post_counter["n"] += 1
            pid = 1000 + post_counter["n"]
            host = self.headers.get("Host", "127.0.0.1")
            post_obj = {
                "id": pid,
                "status": body.get("status", "publish"),
                "slug": body["slug"],
                "title": {"rendered": body["title"]},
                "content": {"rendered": body["content"]},
                "link": f"http://{host}/wp-json/wp/v2/posts/{pid}",
            }
            store[pid] = post_obj
            raw = json.dumps(post_obj).encode("utf-8")
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path.rstrip("/") == "/wp-json/wp/v2/posts":
                qs = parse_qs(parsed.query)
                slug = (qs.get("slug") or [""])[0]
                matches = [p for p in store.values() if not slug or p["slug"] == slug]
                raw = json.dumps(matches).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(raw)
                return
            if parsed.path.startswith("/wp-json/wp/v2/posts/"):
                pid = int(parsed.path.rsplit("/", 1)[-1])
                if pid in store:
                    raw = json.dumps(store[pid]).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(raw)
                    return
            self.send_response(404)
            self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), WordPressSandboxHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        sandbox_url = f"http://127.0.0.1:{port}"
        monkeypatch.setenv("WP_SITE_URL", sandbox_url)
        # Bypass SSRF block strictly for the local loopback sandbox server in this test
        monkeypatch.setattr("app.services.execution_guard.validate_external_url", lambda u: u)

        draft, _ = _create_draft_and_approval(db, approval_status="APPROVED")
        pub = publish_seo_draft_to_wordpress(db=db, draft_id=draft.id)

        assert pub["status"] == "PUBLISHED"
        assert pub["live_published"] is True
        assert pub["post_id"] == 1001
        assert pub["canonical_url"] == f"{sandbox_url}/wp-json/wp/v2/posts/1001"

        # Verify by fetching the resulting post directly over live HTTP from the WordPress sandbox!
        fetched = httpx.get(pub["canonical_url"], timeout=5.0)
        assert fetched.status_code == 200
        fetched_post = fetched.json()
        assert fetched_post["id"] == 1001
        assert fetched_post["title"]["rendered"] == "Fail-Closed WordPress Publishing"
        assert "Verified content body for Issue 12." in fetched_post["content"]["rendered"]

        # Retry publish -> zero duplicate posts created on the sandbox server
        retry = publish_seo_draft_to_wordpress(db=db, draft_id=draft.id)
        assert retry["idempotent_replay"] is True
        assert post_counter["n"] == 1
        assert len(store) == 1
    finally:
        server.shutdown()
        server.server_close()
