"""Adversarial security tests for Decision 1: public role assignment, first-owner bootstrap, invitations, and account isolation."""

import hashlib
import hmac
import json
import os
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["APP_ENV"] = "development"
os.environ.pop("ALLOW_SQLITE_PRODUCTION", None)
TEST_MANAGER_KEY = "test-manager-key-for-sec-hardening-auth-32chars"
os.environ["MANAGER_API_KEY"] = TEST_MANAGER_KEY

from app.db.database import Base, get_db  # noqa: E402
from app.db.models import (  # noqa: E402
    ApprovalRequest,
    AuditLog,
    CustomerRecord,
    InvoiceRecord,
    OrganizationRecord,
    TenantInvitationRecord,
    UserRecord,
)
from app.main import app  # noqa: E402
from app.security.auth import hash_password  # noqa: E402

test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class SecurityHardeningAuthRolesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=test_engine)

    @classmethod
    def tearDownClass(cls):
        Base.metadata.drop_all(bind=test_engine)

    def setUp(self):
        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.db = TestingSessionLocal()
        self.db.query(TenantInvitationRecord).delete()
        self.db.query(InvoiceRecord).delete()
        self.db.query(CustomerRecord).delete()
        self.db.query(ApprovalRequest).delete()
        self.db.query(AuditLog).delete()
        self.db.query(UserRecord).delete()
        self.db.query(OrganizationRecord).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()
        app.dependency_overrides.pop(get_db, None)

    def test_public_register_rejects_privileged_roles_and_defaults_customer(self):
        for role in ("admin", "tenant_admin", "owner", "platform_owner", "platform_admin", "manager"):
            resp = self.client.post(
                "/v1/auth/register",
                json={
                    "email": f"attacker-{role}-{uuid.uuid4().hex[:6]}@evil.co",
                    "password": "StrongPassword123!",
                    "full_name": "Privilege Escalator",
                    "company_name": "Evil Corp",
                    "role": role,
                },
            )
            self.assertEqual(resp.status_code, 403, f"Expected 403 for public role={role!r}, got {resp.text}")

        ok_resp = self.client.post(
            "/v1/auth/register",
            json={
                "email": "safe-user@acme.co",
                "password": "StrongPassword123!",
                "full_name": "Safe User",
                "company_name": "Acme Safe Co",
            },
        )
        self.assertEqual(ok_resp.status_code, 201, ok_resp.text)
        data = ok_resp.json()
        self.assertEqual(data["role"], "customer")
        self.assertFalse(data["portal_access"]["admin"])
        self.assertTrue(data["portal_access"]["customer"])

        member_resp = self.client.post(
            "/v1/auth/register",
            json={
                "email": "member-user@acme2.co",
                "password": "StrongPassword123!",
                "full_name": "Member User",
                "company_name": "Acme Safe Co 2",
                "role": "member",
            },
        )
        self.assertEqual(member_resp.status_code, 201, member_resp.text)
        self.assertEqual(member_resp.json()["role"], "member")
        self.assertFalse(member_resp.json()["portal_access"]["admin"])

    def test_production_unpaid_signup_is_pending_inactive_customer_without_token(self):
        old_env = os.environ.get("APP_ENV")
        os.environ["APP_ENV"] = "production"
        try:
            with patch("app.api.v1.auth.get_email_dispatcher"):
                resp = self.client.post(
                    "/v1/auth/signup",
                    json={
                        "company_name": "Unpaid Production Co",
                        "email": "unpaid-owner@prodco.in",
                        "password": "StrongPassword123!",
                        "full_name": "Pending Founder",
                        "package_key": "company_os_starter",
                        "payment_provider": "afw_directpay",
                    },
                )
        finally:
            if old_env is not None:
                os.environ["APP_ENV"] = old_env
            else:
                os.environ.pop("APP_ENV", None)

        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()
        self.assertEqual(data["status"], "PENDING_PAYMENT")
        self.assertEqual(data["role"], "customer")
        self.assertIsNone(data["access_token"])

        user = self.db.get(UserRecord, data["user_id"])
        org = self.db.get(OrganizationRecord, data["org_id"])
        self.assertFalse(user.is_active)
        self.assertFalse(org.is_active)
        self.assertEqual(user.role, "customer")

        login_resp = self.client.post(
            "/v1/auth/login",
            json={"email": "unpaid-owner@prodco.in", "password": "StrongPassword123!", "portal": "customer"},
        )
        self.assertEqual(login_resp.status_code, 403)

    def test_first_owner_signup_bootstrap_scoped_to_own_org_and_blocked_on_platform_ops(self):
        with patch("app.api.v1.auth.get_email_dispatcher"):
            s1 = self.client.post(
                "/v1/auth/signup",
                json={
                    "company_name": "Alpha Logistics Pvt Ltd",
                    "email": "founder@alphalog.in",
                    "password": "StrongPassword123!",
                    "full_name": "Alpha Founder",
                    "package_key": "company_os_starter",
                },
            )
            s2 = self.client.post(
                "/v1/auth/signup",
                json={
                    "company_name": "Beta Retail Pvt Ltd",
                    "email": "founder@betaretail.in",
                    "password": "StrongPassword123!",
                    "full_name": "Beta Founder",
                    "package_key": "company_os_starter",
                },
            )
        self.assertEqual(s1.status_code, 201)
        self.assertEqual(s2.status_code, 201)
        alpha = s1.json()
        beta = s2.json()
        self.assertEqual(alpha["role"], "tenant_admin")
        self.assertTrue(alpha["access_token"])
        headers_a = {"Authorization": f"Bearer {alpha['access_token']}"}

        # Platform-only account routes must reject tenant_admin with 403
        for method, path, body in (
            ("POST", "/v1/accounts/orgs", {"name": "Injected Org"}),
            ("POST", f"/v1/accounts/orgs/{alpha['org_id']}/invoices", {"amount": 1000, "currency": "INR"}),
            ("GET", "/v1/accounts/reconciliation", None),
        ):
            r = self.client.request(method, path, headers=headers_a, json=body)
            self.assertEqual(r.status_code, 403, f"Tenant token must not access platform route {method} {path}: {r.text}")

        # Tenant A cannot access or invite into Tenant B
        cross_invite = self.client.post(
            f"/v1/accounts/orgs/{beta['org_id']}/invitations",
            headers=headers_a,
            json={"email": "spy@alphalog.in", "role": "member"},
        )
        self.assertEqual(cross_invite.status_code, 403)

    def test_invitation_lifecycle_single_use_and_approved_tenant_admin_grant(self):
        with patch("app.api.v1.auth.get_email_dispatcher"):
            s1 = self.client.post(
                "/v1/auth/signup",
                json={
                    "company_name": "Gamma Tech",
                    "email": "owner@gammatech.in",
                    "password": "StrongPassword123!",
                    "full_name": "Gamma Owner",
                    "package_key": "company_os_starter",
                },
            )
        self.assertEqual(s1.status_code, 201)
        org_id = s1.json()["org_id"]
        headers_owner = {"Authorization": f"Bearer {s1.json()['access_token']}"}

        # Subsequent tenant_admin invitation without approval_id is blocked
        blocked_admin_inv = self.client.post(
            f"/v1/accounts/orgs/{org_id}/invitations",
            headers=headers_owner,
            json={"email": "co-admin@gammatech.in", "role": "tenant_admin"},
        )
        self.assertEqual(blocked_admin_inv.status_code, 403)

        # Create normal member invitation & join via /v1/auth/register?invite_token
        mem_inv = self.client.post(
            f"/v1/accounts/orgs/{org_id}/invitations",
            headers=headers_owner,
            json={"email": "dev@gammatech.in", "role": "member"},
        )
        self.assertEqual(mem_inv.status_code, 201, mem_inv.text)
        mem_token = mem_inv.json()["invitation_token"]

        joined = self.client.post(
            "/v1/auth/register",
            json={
                "email": "dev@gammatech.in",
                "password": "MemberPassword123!",
                "full_name": "Gamma Engineer",
                "invite_token": mem_token,
            },
        )
        self.assertEqual(joined.status_code, 201, joined.text)
        joined_data = joined.json()
        self.assertEqual(joined_data["org_id"], org_id)
        self.assertEqual(joined_data["role"], "member")

        # Single-use replay of the same invite token must fail
        replay = self.client.post(
            "/v1/auth/invitations/accept",
            json={"token": mem_token, "password": "NewPassword123!", "full_name": "Replay"},
        )
        self.assertEqual(replay.status_code, 409)

        # Promoting member to tenant_admin without approval fails; with APPROVED ApprovalRequest succeeds
        no_appr = self.client.post(
            f"/v1/accounts/orgs/{org_id}/users/{joined_data['user_id']}/role",
            headers=headers_owner,
            json={"role": "tenant_admin"},
        )
        self.assertEqual(no_appr.status_code, 403)

        appr = ApprovalRequest(
            id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            action="grant_tenant_admin",
            detail={"org_id": org_id, "email": "dev@gammatech.in", "user_id": joined_data["user_id"]},
            idempotency_key=f"appr-1-{uuid.uuid4().hex}",
            request_hash=f"hash-1-{uuid.uuid4().hex}",
            status="APPROVED",
            requested_by="owner@gammatech.in",
            decided_by="owner@gammatech.in",
        )
        self.db.add(appr)
        self.db.commit()

        promoted = self.client.post(
            f"/v1/accounts/orgs/{org_id}/users/{joined_data['user_id']}/role",
            headers=headers_owner,
            json={"role": "tenant_admin", "approval_id": appr.id},
        )
        self.assertEqual(promoted.status_code, 200, promoted.text)
        self.assertEqual(promoted.json()["role"], "tenant_admin")

        # Invitation via /v1/auth/invitations/accept for approved co-admin
        appr2 = ApprovalRequest(
            id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            action="grant_tenant_admin",
            detail={"org_id": org_id, "email": "ops-lead@gammatech.in"},
            idempotency_key=f"appr-2-{uuid.uuid4().hex}",
            request_hash=f"hash-2-{uuid.uuid4().hex}",
            status="APPROVED",
            requested_by="owner@gammatech.in",
            decided_by="owner@gammatech.in",
        )
        self.db.add(appr2)
        self.db.commit()

        admin_inv = self.client.post(
            f"/v1/accounts/orgs/{org_id}/invitations",
            headers=headers_owner,
            json={"email": "ops-lead@gammatech.in", "role": "tenant_admin", "approval_id": appr2.id},
        )
        self.assertEqual(admin_inv.status_code, 201, admin_inv.text)
        accepted = self.client.post(
            "/v1/auth/invitations/accept",
            json={
                "token": admin_inv.json()["invitation_token"],
                "password": "OpsLeadPassword123!",
                "full_name": "Ops Lead",
            },
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["role"], "tenant_admin")
        self.assertEqual(accepted.json()["org_id"], org_id)

    def test_deactivated_user_and_deactivated_org_jwt_fail_closed(self):
        org = OrganizationRecord(
            id=str(uuid.uuid4()),
            name="Revocable Org",
            slug=f"revocable-{uuid.uuid4().hex[:6]}",
            tier="starter",
            is_active=True,
        )
        user = UserRecord(
            id=str(uuid.uuid4()),
            org_id=org.id,
            email=f"live-{uuid.uuid4().hex[:6]}@revocable.co",
            full_name="Live User",
            role="customer",
            password_hash=hash_password("Pass123456!"),
            is_active=True,
        )
        self.db.add_all([org, user])
        self.db.commit()

        login = self.client.post(
            "/v1/auth/login",
            json={"email": user.email, "password": "Pass123456!", "portal": "customer"},
        )
        self.assertEqual(login.status_code, 200)
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        self.assertEqual(self.client.get("/v1/auth/me", headers=headers).status_code, 200)

        # Deactivate user -> immediate 403 on existing JWT
        user.is_active = False
        self.db.commit()
        self.assertEqual(self.client.get("/v1/auth/me", headers=headers).status_code, 403)

        # Re-activate user, deactivate organization -> immediate 403 on JWT + login
        user.is_active = True
        org.is_active = False
        self.db.commit()
        self.assertEqual(self.client.get("/v1/auth/me", headers=headers).status_code, 403)
        self.assertEqual(
            self.client.post(
                "/v1/auth/login",
                json={"email": user.email, "password": "Pass123456!", "portal": "customer"},
            ).status_code,
            403,
        )

    def test_production_payment_verified_first_owner_bootstrap_promotion(self):
        from app.services.catalog import CATALOG

        owner_email = f"verified-owner-{uuid.uuid4().hex[:6]}@zenithmfg.in"
        with patch.dict(os.environ, {"APP_ENV": "production", "RAZORPAY_WEBHOOK_SECRET": "test-rzp-secret-32"}):
            with patch("app.api.v1.auth.get_email_dispatcher"):
                s_resp = self.client.post(
                    "/v1/auth/signup",
                    json={
                        "company_name": "Zenith Manufacturing Co",
                        "email": owner_email,
                        "password": "StrongPassword123!",
                        "full_name": "Zenith Founder",
                        "package_key": "company_os_starter",
                        "payment_provider": "razorpay",
                    },
                )
            self.assertEqual(s_resp.status_code, 201, s_resp.text)
            signup_data = s_resp.json()
            self.assertEqual(signup_data["role"], "customer")
            self.assertIsNone(signup_data["access_token"])

            # Blocked before verified payment settlement
            pre_login = self.client.post(
                "/v1/auth/login",
                json={"email": owner_email, "password": "StrongPassword123!", "portal": "admin"},
            )
            self.assertEqual(pre_login.status_code, 403)

            # Invalid webhook signature must fail closed with 401
            pkg = CATALOG["company_os_starter"]
            webhook_payload = {
                "id": f"evt_{uuid.uuid4().hex[:14]}",
                "event": "payment.captured",
                "payload": {
                    "payment": {
                        "entity": {
                            "id": f"pay_{uuid.uuid4().hex[:14]}",
                            "amount": int(pkg.price_inr * 100),
                            "currency": "INR",
                            "email": owner_email,
                            "notes": {
                                "email": owner_email,
                                "package_key": pkg.key,
                                "company_name": "Zenith Manufacturing Co",
                            },
                        }
                    }
                },
            }
            raw = json.dumps(webhook_payload).encode("utf-8")
            bad_wh = self.client.post(
                "/v1/webhooks/payment",
                content=raw,
                headers={"Content-Type": "application/json", "x-razorpay-signature": "forged-sig"},
            )
            self.assertEqual(bad_wh.status_code, 401)

            # Valid HMAC-signed webhook activates org + promotes ONLY first_owner_candidate to tenant_admin
            sig = hmac.new(b"test-rzp-secret-32", raw, hashlib.sha256).hexdigest()
            with patch("app.services.provisioning.get_email_dispatcher"):
                ok_wh = self.client.post(
                    "/v1/webhooks/payment",
                    content=raw,
                    headers={"Content-Type": "application/json", "x-razorpay-signature": sig},
                )
            self.assertEqual(ok_wh.status_code, 200, ok_wh.text)

        self.db.expire_all()
        promoted_user = self.db.get(UserRecord, signup_data["user_id"])
        active_org = self.db.get(OrganizationRecord, signup_data["org_id"])
        self.assertTrue(promoted_user.is_active)
        self.assertTrue(active_org.is_active)
        self.assertEqual(promoted_user.role, "tenant_admin")

        boot_audit = (
            self.db.query(AuditLog)
            .filter(AuditLog.action == "payment_verified_tenant_admin_bootstrap")
            .all()
        )
        self.assertTrue(any((row.output_payload or {}).get("user_id") == promoted_user.id for row in boot_audit))

        # Founder can now log into admin portal as tenant_admin scoped to their org
        post_login = self.client.post(
            "/v1/auth/login",
            json={"email": owner_email, "password": "StrongPassword123!", "portal": "admin"},
        )
        self.assertEqual(post_login.status_code, 200, post_login.text)
        login_data = post_login.json()
        self.assertEqual(login_data["role"], "tenant_admin")
        self.assertEqual(login_data["org_id"], signup_data["org_id"])
        self.assertTrue(login_data["portal_access"]["admin"])

    def test_invitation_expiry_wrong_email_and_approval_replay_protection(self):
        with patch("app.api.v1.auth.get_email_dispatcher"):
            s1 = self.client.post(
                "/v1/auth/signup",
                json={
                    "company_name": "Delta Security Co",
                    "email": "founder@deltasec.in",
                    "password": "StrongPassword123!",
                    "full_name": "Delta Founder",
                    "package_key": "company_os_starter",
                },
            )
        self.assertEqual(s1.status_code, 201)
        org_id = s1.json()["org_id"]
        headers_owner = {"Authorization": f"Bearer {s1.json()['access_token']}"}

        # 1. Wrong email trying to claim invite token -> 403
        alice_inv = self.client.post(
            f"/v1/accounts/orgs/{org_id}/invitations",
            headers=headers_owner,
            json={"email": "alice@deltasec.in", "role": "member"},
        )
        self.assertEqual(alice_inv.status_code, 201)
        alice_token = alice_inv.json()["invitation_token"]

        wrong_email = self.client.post(
            "/v1/auth/register",
            json={
                "email": "intruder@deltasec.in",
                "password": "Password123!",
                "full_name": "Intruder",
                "invite_token": alice_token,
            },
        )
        self.assertEqual(wrong_email.status_code, 403)

        # 2. Expired invitation -> 410 GONE on both accept & register, plus replay still returns 410
        exp_inv = self.client.post(
            f"/v1/accounts/orgs/{org_id}/invitations",
            headers=headers_owner,
            json={"email": "expired-user@deltasec.in", "role": "member"},
        )
        self.assertEqual(exp_inv.status_code, 201)
        exp_id = exp_inv.json()["invitation_id"]
        exp_token = exp_inv.json()["invitation_token"]

        inv_row = self.db.get(TenantInvitationRecord, exp_id)
        inv_row.expires_at = datetime.now(UTC) - timedelta(minutes=10)
        self.db.commit()

        acc_expired = self.client.post(
            "/v1/auth/invitations/accept",
            json={"token": exp_token, "password": "Password123!", "full_name": "Late User"},
        )
        self.assertEqual(acc_expired.status_code, 410, acc_expired.text)

        replay_expired = self.client.post(
            "/v1/auth/register",
            json={
                "email": "expired-user@deltasec.in",
                "password": "Password123!",
                "full_name": "Late Replay",
                "invite_token": exp_token,
            },
        )
        self.assertEqual(replay_expired.status_code, 410, replay_expired.text)

        self.db.expire_all()
        self.assertEqual(self.db.get(TenantInvitationRecord, exp_id).status, "EXPIRED")

        # 3. Single-use ApprovalRequest replay protection (409 Conflict) across promotion & admin invites
        # Join two ordinary members first
        joined_ids = []
        for idx, addr in enumerate(("u1@deltasec.in", "u2@deltasec.in")):
            inv = self.client.post(
                f"/v1/accounts/orgs/{org_id}/invitations",
                headers=headers_owner,
                json={"email": addr, "role": "member"},
            )
            self.assertEqual(inv.status_code, 201)
            acc = self.client.post(
                "/v1/auth/invitations/accept",
                json={"token": inv.json()["invitation_token"], "password": f"MemberPass{idx}!", "full_name": f"User {idx}"},
            )
            self.assertEqual(acc.status_code, 200)
            joined_ids.append(acc.json()["user_id"])

        appr_promo = ApprovalRequest(
            id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            action="grant_tenant_admin",
            detail={"org_id": org_id},
            idempotency_key=f"appr-promo-{uuid.uuid4().hex}",
            request_hash=f"hash-promo-{uuid.uuid4().hex}",
            status="APPROVED",
            requested_by="founder@deltasec.in",
            decided_by="founder@deltasec.in",
        )
        appr_inv = ApprovalRequest(
            id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            action="grant_tenant_admin",
            detail={"org_id": org_id},
            idempotency_key=f"appr-inv-{uuid.uuid4().hex}",
            request_hash=f"hash-inv-{uuid.uuid4().hex}",
            status="APPROVED",
            requested_by="founder@deltasec.in",
            decided_by="founder@deltasec.in",
        )
        self.db.add_all([appr_promo, appr_inv])
        self.db.commit()

        # First promotion with appr_promo succeeds; replay to promote u2 OR invite co-admin fails with 409
        p1 = self.client.post(
            f"/v1/accounts/orgs/{org_id}/users/{joined_ids[0]}/role",
            headers=headers_owner,
            json={"role": "tenant_admin", "approval_id": appr_promo.id},
        )
        self.assertEqual(p1.status_code, 200, p1.text)

        p2_replay = self.client.post(
            f"/v1/accounts/orgs/{org_id}/users/{joined_ids[1]}/role",
            headers=headers_owner,
            json={"role": "tenant_admin", "approval_id": appr_promo.id},
        )
        self.assertEqual(p2_replay.status_code, 409, p2_replay.text)

        inv_replay_promo = self.client.post(
            f"/v1/accounts/orgs/{org_id}/invitations",
            headers=headers_owner,
            json={"email": "coadmin-replay@deltasec.in", "role": "tenant_admin", "approval_id": appr_promo.id},
        )
        self.assertEqual(inv_replay_promo.status_code, 409, inv_replay_promo.text)

        # First admin invite with appr_inv succeeds; replay for another admin invite or role promotion fails with 409
        inv_ok = self.client.post(
            f"/v1/accounts/orgs/{org_id}/invitations",
            headers=headers_owner,
            json={"email": "coadmin1@deltasec.in", "role": "tenant_admin", "approval_id": appr_inv.id},
        )
        self.assertEqual(inv_ok.status_code, 201, inv_ok.text)

        inv_replay = self.client.post(
            f"/v1/accounts/orgs/{org_id}/invitations",
            headers=headers_owner,
            json={"email": "coadmin2@deltasec.in", "role": "tenant_admin", "approval_id": appr_inv.id},
        )
        self.assertEqual(inv_replay.status_code, 409, inv_replay.text)

        promo_replay_inv = self.client.post(
            f"/v1/accounts/orgs/{org_id}/users/{joined_ids[1]}/role",
            headers=headers_owner,
            json={"role": "tenant_admin", "approval_id": appr_inv.id},
        )
        self.assertEqual(promo_replay_inv.status_code, 409, promo_replay_inv.text)


if __name__ == "__main__":
    unittest.main()
