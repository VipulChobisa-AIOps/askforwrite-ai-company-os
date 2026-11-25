"""Tests for autonomous sales/marketing HITL automation, HTTPS email APIs, and IMAP bounce/reply sync."""

from __future__ import annotations

import json
import os
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.db.database import Base, SessionLocal, engine
from app.db.models import (
    ApprovalRequest,
    LeadRecordRow,
    OutreachRecord,
    P2ProspectDossierRecord,
    TaskRecord,
)
from app.services.approvals import decide_approval
from app.services.email_dispatcher import (
    BrevoEmailDispatcher,
    ResendEmailDispatcher,
    SmtpEmailDispatcher,
    get_email_dispatcher,
)
from app.services.inbox_sync import process_inbox_messages
from app.services.suppression import is_db_suppressed
from app.services.p2_outreach_pipeline import prepare_p2_outreach
from app.services.shift_scheduler import run_autonomous_shift


class AutonomousSalesMarketingAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        Base.metadata.create_all(bind=engine)
        self.db = SessionLocal()

    def tearDown(self) -> None:
        self.db.close()

    def test_https_email_dispatchers_and_auto_factory_selection(self) -> None:
        """Resend & Brevo HTTPS dispatchers work over port 443 and respect staging simulation guards."""
        env_patch = {
            "APP_ENV": "production",
            "ENABLE_EXTERNAL_SIDE_EFFECTS": "true",
            "OUTREACH_DISPATCH_PROVIDER": "auto",
            "RESEND_API_KEY": "re_test_123",
            "RESEND_FROM_EMAIL": "AskforWrite AI Solutions <info@os.askforwrite.com>",
            "OUTREACH_REPLY_TO_EMAIL": "info@askforwrite.in",
            "BREVO_API_KEY": "",
            "SMTP_HOST": "smtp.hostinger.com",
            "SMTP_MODE": "smtp",
        }
        with patch.dict(os.environ, env_patch, clear=False):
            disp = get_email_dispatcher()
            self.assertIsInstance(disp, ResendEmailDispatcher)

            captured_req = {}

            def _fake_urlopen(req, timeout=15.0):
                captured_req["body"] = json.loads(req.data.decode("utf-8"))
                m = MagicMock()
                m.read.return_value = json.dumps({"id": "re_msg_999"}).encode("utf-8")
                m.__enter__.return_value = m
                return m

            with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
                receipt = disp.send("buyer@acme.in", "Test Subject", "Hello buyer", from_email="info@askforwrite.in")
            self.assertEqual(receipt["provider"], "resend")
            self.assertEqual(receipt["status"], "delivered")
            self.assertEqual(receipt["message_id"], "re_msg_999")
            self.assertEqual(captured_req["body"]["from"], "AskforWrite AI Solutions <info@os.askforwrite.com>")
            self.assertEqual(captured_req["body"]["reply_to"], "info@askforwrite.in")

        env_brevo = {**env_patch, "RESEND_API_KEY": "", "BREVO_API_KEY": "xkeysib-test-123"}
        with patch.dict(os.environ, env_brevo, clear=False):
            disp_b = get_email_dispatcher()
            self.assertIsInstance(disp_b, BrevoEmailDispatcher)

            mock_resp_b = MagicMock()
            mock_resp_b.read.return_value = json.dumps({"messageId": "<brevo-123@brevo.com>"}).encode("utf-8")
            mock_resp_b.__enter__.return_value = mock_resp_b
            with patch("urllib.request.urlopen", return_value=mock_resp_b):
                receipt_b = disp_b.send("buyer@acme.in", "Test Brevo", "Hello Brevo")
            self.assertEqual(receipt_b["provider"], "brevo")
            self.assertEqual(receipt_b["status"], "delivered")
            self.assertEqual(receipt_b["message_id"], "<brevo-123@brevo.com>")

        env_smtp = {**env_patch, "RESEND_API_KEY": "", "BREVO_API_KEY": ""}
        with patch.dict(os.environ, env_smtp, clear=False):
            self.assertIsInstance(get_email_dispatcher(), SmtpEmailDispatcher)

        # Staging guard blocks external HTTPS sends cleanly
        with patch.dict(os.environ, {**env_patch, "ENABLE_EXTERNAL_SIDE_EFFECTS": "false"}, clear=False):
            sim_receipt = ResendEmailDispatcher(api_key="re_test_123").send("buyer@acme.in", "Sim", "Body")
            self.assertTrue(sim_receipt["simulated"])

    def _create_lead_and_outreach(self, email_addr: str, status: str = "SENT") -> tuple[LeadRecordRow, OutreachRecord]:
        lead_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        self.db.add(TaskRecord(id=task_id, correlation_id=str(uuid.uuid4()), objective="Test lead task", status="COMPLETED", result={}))
        lead = LeadRecordRow(
            id=lead_id,
            task_id=task_id,
            company=f"Agency {lead_id[:6]}",
            website=f"https://{email_addr.split('@')[-1]}",
            industry="WordPress B2B Agency",
            geography="India",
            observed_signals=["WordPress site"],
            sources=[{"source": "unit_test"}],
            product_match="managed_seo_content_pilot",
            fit_score=0.9,
            confidence=0.9,
            public_contact_channel=email_addr,
            recommended_next_step="outreach",
            do_not_contact=False,
            status="CONTACTED",
            last_checked=datetime.now(UTC),
        )
        self.db.add(lead)
        dom = email_addr.split("@")[-1]
        dossier = P2ProspectDossierRecord(
            id=str(uuid.uuid4()),
            lead_id=lead_id,
            normalized_company_key=f"agency-{lead_id[:6]}",
            normalized_domain=dom,
            business_category="WordPress Agency",
            location="India",
            source_url=lead.website,
            source_type="manual_verified_research",
            collected_at=datetime.now(UTC),
            is_synthetic=False,
            public_contacts_json=[{"email": email_addr, "verified": True}],
            agency_profile_json={"services": ["WordPress"]},
            research_claims_json=[],
            qualification_breakdown_json={"total": 90},
            qualification_score=90.0,
            research_brief_json={},
            pipeline_status="CONTACTED",
            follow_up_at=datetime.now(UTC) - timedelta(hours=2),
            response_history_json=[],
            recommended_sku="managed_seo_content_pilot",
            commercial_value_inr=4999,
            currency="INR",
            payment_status="UNPAID",
            activation_status="PENDING",
        )
        self.db.add(dossier)
        outreach = OutreachRecord(
            id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            lead_id=lead_id,
            channel="email",
            recipient_email=email_addr,
            recipient_name=f"{lead.company} Team",
            subject="3 quick WordPress SEO fixes",
            body_text="Hello team",
            status=status,
            idempotency_key=f"test-out-{uuid.uuid4().hex[:10]}",
            sent_at=datetime.now(UTC) - timedelta(days=5),
            metadata_json={"p2_commercial": True},
        )
        self.db.add(outreach)
        self.db.commit()
        return lead, outreach

    def test_inbox_sync_handles_bounce_optout_and_positive_reply_hitl_draft(self) -> None:
        """Autonomous inbox sync marks bounces, suppresses opt-outs, and stages HITL scope replies."""
        uid = uuid.uuid4().hex[:6]
        bounce_email = f"bounce-{uid}@wpoets-test.in"
        optout_email = f"optout-{uid}@midnay-test.in"
        reply_email = f"buyer-{uid}@digitech-test.in"

        _, rec_bounce = self._create_lead_and_outreach(bounce_email, status="SENT")
        lead_optout, _ = self._create_lead_and_outreach(optout_email, status="SENT")
        lead_reply, _ = self._create_lead_and_outreach(reply_email, status="SENT")

        messages = [
            {
                "uid": f"b-{uid}",
                "from": "Mail Delivery System <mailer-daemon@bounce.mailchannels.net>",
                "subject": "Returned mail",
                "body": f"from info@askforwrite.in and addressed to {bounce_email}.\nResponse: 550 5.7.1 [SS] Blocked.",
            },
            {
                "uid": f"u-{uid}",
                "from": f"Founder <{optout_email}>",
                "subject": "Re: 3 quick WordPress SEO fixes",
                "body": "Please unsubscribe us from future emails.",
            },
            {
                "uid": f"r-{uid}",
                "from": f"Director <{reply_email}>",
                "subject": "Re: 3 quick WordPress SEO fixes",
                "body": "Thanks Vipul, please send scope for the Rs 4,999 pilot!",
            },
        ]

        res = process_inbox_messages(self.db, messages)
        self.assertEqual(res["bounces_marked_count"], 1)
        self.assertEqual(res["optouts_recorded_count"], 1)
        self.assertEqual(res["replies_staged_count"], 1)

        self.db.refresh(rec_bounce)
        self.assertEqual(rec_bounce.status, "BOUNCED")
        self.assertIn("550 5.7.1", rec_bounce.error_message or "")

        suppressed, reason = is_db_suppressed(self.db, optout_email, lead_id=lead_optout.id)
        self.assertTrue(suppressed)
        self.assertTrue(bool(reason))

        # Positive reply auto-staged a PENDING_APPROVAL scope email with auto_dispatch_on_approval=True
        staged_id = res["replies_staged"][0]["staged_outreach_id"]
        staged_rec = self.db.get(OutreachRecord, staged_id)
        self.assertIsNotNone(staged_rec)
        self.assertEqual(staged_rec.status, "PENDING_APPROVAL")
        self.assertTrue((staged_rec.metadata_json or {}).get("auto_dispatch_on_approval"))
        self.assertIn("4,999", staged_rec.body_text)
        dossier_reply = self.db.query(P2ProspectDossierRecord).filter_by(lead_id=lead_reply.id).first()
        self.assertEqual(dossier_reply.pipeline_status, "REPLIED")

    def test_owner_one_click_approval_auto_dispatches_p2_and_fails_closed_on_error(self) -> None:
        """Approving a P2 outreach with auto-dispatch enabled sends automatically and never fakes success on failure."""
        uid = uuid.uuid4().hex[:6]
        lead, _ = self._create_lead_and_outreach(f"approve-{uid}@agency-test.in", status="BOUNCED")
        prep = prepare_p2_outreach(
            self.db,
            lead_id=lead.id,
            recipient_email=f"approve2-{uid}@agency-test.in",
            recipient_name="Agency Team",
            subject_override="Pilot Scope",
            body_override="Hello — reply unsubscribe anytime.",
            allow_follow_up=True,
            idempotency_key=f"auto-disp-test-{uid}",
        )
        appr_id = prep["approval_id"]
        out_id = prep["outreach_id"]

        with patch.dict(os.environ, {"ENABLE_AUTONOMOUS_SALES_AUTO_DISPATCH": "true", "APP_ENV": "development"}, clear=False):
            with patch("app.services.p2_outreach_pipeline.dispatch_p2_outreach", side_effect=RuntimeError("SMTP blocked")):
                res = decide_approval(
                    db=self.db,
                    approval_id=appr_id,
                    decision="APPROVED",
                    decided_by="owner",
                    reason="Approve test",
                    correlation_id=str(uuid.uuid4()),
                )
        self.assertEqual(res["status"], "APPROVED")
        self.assertFalse(res["external_action_performed"])
        self.assertEqual(res["auto_executed_action"], "p2_outreach_dispatch_failed")
        appr = self.db.get(ApprovalRequest, appr_id)
        self.assertEqual(appr.status, "APPROVED")
        out_row = self.db.get(OutreachRecord, out_id)
        self.assertNotEqual(out_row.status, "DISPATCHED")

    def test_sales_marketing_shift_stages_single_followup_and_skips_bounced(self) -> None:
        """sales_marketing_cycle runs inbox_sync + follow_up_closer, staging 1 HITL follow-up only for cleanly SENT due leads."""
        uid = uuid.uuid4().hex[:6]
        lead_due, _ = self._create_lead_and_outreach(f"due-{uid}@agency-test.in", status="SENT")
        lead_bounced, _ = self._create_lead_and_outreach(f"bounced-{uid}@agency-test.in", status="BOUNCED")

        with patch("app.services.shift_scheduler.discover_smb_leads", return_value=[]):
            res = run_autonomous_shift(db=self.db, shift_type="sales_marketing_cycle")

        steps = res["step_results"]
        self.assertIn("inbox_sync", steps)
        self.assertIn("follow_up_closer", steps)
        self.assertEqual(steps["order_fulfillment"]["status"], "SKIPPED")
        staged_ids = [f["lead_id"] for f in steps["follow_up_closer"]["followups"]]
        self.assertIn(lead_due.id, staged_ids)
        self.assertNotIn(lead_bounced.id, staged_ids)

    def test_inbox_sync_ignores_stale_or_mailchannels_bounce_after_resend_redelivery(self) -> None:
        """Historical MailChannels NDRs in INBOX must not re-bounce freshly Resend-delivered outreach."""
        uid = uuid.uuid4().hex[:6]
        target_email = f"retry-{uid}@agency-resend.in"
        lead, rec = self._create_lead_and_outreach(target_email, status="SENT")
        dossier = self.db.query(P2ProspectDossierRecord).filter_by(lead_id=lead.id).first()
        if dossier:
            dossier.follow_up_at = None
            self.db.add(dossier)
        rec.sent_at = datetime.now(UTC)
        rec.error_message = None
        rec.metadata_json = {
            "p2_commercial": True,
            "dispatch_receipt": {"provider": "resend", "status": "delivered", "message_id": "re_live_123"},
            "external_sent": True,
        }
        self.db.add(rec)
        self.db.commit()

        old_date = (datetime.now(UTC) - timedelta(days=2)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        messages = [
            {
                "uid": f"old-mc-{uid}",
                "from": "Mail Delivery System <mailer-daemon@bounce.mailchannels.net>",
                "subject": "Returned mail",
                "date": old_date,
                "body": f"addressed to {target_email}.\nResponse: 550 5.7.1 [SS] Blocked.",
            }
        ]
        res = process_inbox_messages(self.db, messages)
        self.assertEqual(res["bounces_marked_count"], 0)
        self.db.refresh(rec)
        self.assertEqual(rec.status, "SENT")

    def test_start_production_redacts_sensitive_optional_vars(self) -> None:
        """Startup diagnostics must redact secrets, PEM keys, and database URLs."""
        import importlib.util
        from pathlib import Path

        script_path = Path(__file__).resolve().parents[1] / "scripts" / "start_production.py"
        spec = importlib.util.spec_from_file_location("start_production_under_test", script_path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _format_optional_var_value = mod._format_optional_var_value

        self.assertEqual(
            _format_optional_var_value("DATABASE_URL_UNPOOLED", "postgresql://user:supersecret@host/db"),
            "configured (redacted)",
        )
        self.assertEqual(
            _format_optional_var_value("TRUST_ENGINE_PRIVATE_KEY_PEM", "-----BEGIN PRIVATE KEY-----"),
            "configured (redacted)",
        )
        self.assertEqual(
            _format_optional_var_value("RESEND_API_KEY", "re_fake_secret_123"),
            "configured (redacted)",
        )
        self.assertEqual(
            _format_optional_var_value("RESEND_FROM_EMAIL", "AskforWrite AI Solutions <info@os.askforwrite.com>"),
            "AskforWrite AI Solutions <info@os.askforwrite.com>",
        )

    def test_autonomous_shift_deduplicates_pending_seo_approvals(self) -> None:
        """Repeated autonomous shifts must never flood Owner Approvals with duplicate pending SEO drafts."""
        with patch("app.services.shift_scheduler.discover_smb_leads", return_value=[]):
            run_autonomous_shift(db=self.db, shift_type="sales_marketing_cycle")
            count_after_first = (
                self.db.query(ApprovalRequest)
                .filter_by(action="live_publishing", status="PENDING")
                .count()
            )
            res2 = run_autonomous_shift(db=self.db, shift_type="sales_marketing_cycle")
            count_after_second = (
                self.db.query(ApprovalRequest)
                .filter_by(action="live_publishing", status="PENDING")
                .count()
            )

        self.assertEqual(count_after_second, count_after_first)
        by_net = {d["target_network"]: d.get("status") for d in res2["step_results"]["owned_media_seo"]["staged_drafts"]}
        self.assertEqual(by_net["askforwrite.com"], "SKIPPED_PENDING_APPROVAL_EXISTS")
        self.assertEqual(by_net["ask4write.com"], "SKIPPED_PENDING_APPROVAL_EXISTS")
        self.assertEqual(by_net["askforwrite.info"], "SKIPPED_PENDING_APPROVAL_EXISTS")
        self.assertEqual(by_net["askforwrite.in"], "SKIPPED_NO_WP_REST_ENDPOINT")
        self.assertEqual(by_net["shop.ask4write.com"], "SKIPPED_NO_WP_REST_ENDPOINT")
        self.assertEqual(by_net["node.askforwrite.in"], "SKIPPED_NO_WP_REST_ENDPOINT")

    def test_wordpress_html_renderer_and_multisite_target_resolution(self) -> None:
        """WordPress publisher converts Markdown+JSON-LD to clean HTML and resolves per-site credentials."""
        from app.services.wordpress_publisher import (
            get_live_wordpress_networks,
            render_wordpress_html,
            resolve_wordpress_target,
        )

        self.assertEqual(
            set(get_live_wordpress_networks().keys()),
            {"askforwrite.com", "ask4write.com", "askforwrite.info"},
        )

        md = (
            "# Duplicate H1 Title\n\n"
            "**Executive Summary:** Clean *semantic* `HTML` with [AskforWrite](https://askforwrite.com).\n\n"
            "## Key Architecture\n"
            "- **Item One**: Value\n"
            "- Item Two\n\n"
            "```json\n"
            '{"@context": "https://schema.org", "@type": "Article", "headline": "Test"}\n'
            "```\n"
        )
        rendered = render_wordpress_html(md)
        self.assertNotIn("<h1>", rendered)
        self.assertNotIn("Duplicate H1 Title", rendered)
        self.assertIn("<h2>Key Architecture</h2>", rendered)
        self.assertIn("<strong>Executive Summary:</strong>", rendered)
        self.assertIn("<em>semantic</em>", rendered)
        self.assertIn('href="https://askforwrite.com"', rendered)
        self.assertIn("<ul>\n<li><strong>Item One</strong>: Value</li>", rendered)
        self.assertIn('<script type="application/ld+json">', rendered)
        self.assertNotIn("```json", rendered)

        # Already-HTML input passes through untouched
        pre_html = "<h2>Already HTML</h2><p>Clean body.</p>"
        self.assertEqual(render_wordpress_html(pre_html), pre_html)

        # Per-site credential resolution takes precedence over global WP_SITE_URL
        with patch.dict(
            os.environ,
            {
                "WP_SITE_URL": "https://askforwrite.in",
                "WP_USERNAME": "global_user",
                "WP_APP_PASSWORD": "global_pass",
                "WP_USERNAME_ASKFORWRITE_COM": "wp_com_user",
                "WP_APP_PASSWORD_ASKFORWRITE_COM": "xxxx yyyy zzzz wwww",
            },
            clear=False,
        ):
            url_com, user_com, pass_com = resolve_wordpress_target("askforwrite.com")
            self.assertEqual(url_com, "https://askforwrite.com")
            self.assertEqual(user_com, "wp_com_user")
            self.assertEqual(pass_com, "xxxx yyyy zzzz wwww")

            url_info, user_info, _ = resolve_wordpress_target("askforwrite.info")
            self.assertEqual(url_info, "https://askforwrite.in")
            self.assertEqual(user_info, "global_user")
