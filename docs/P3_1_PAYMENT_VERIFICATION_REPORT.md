# P3.1 Razorpay & PayPal Payment Verification Report

**Modules Verified:**
- `app/services/payment_razorpay.py` (`RazorpayProvider`)
- `app/services/payment_paypal.py` (`PayPalProvider`)
- `app/services/payment.py` (`inspect_payment_provider_config`)
- `app/api/v1/webhooks.py` (`POST /v1/webhooks/payment`)
- `app/services/p2_proposal_settlement.py` (`reconcile_verified_payment`, `record_payment_failure_or_refund`)
- `app/services/p3_revenue_growth.py` (`record_subscription_lifecycle_event`, `handle_payment_failure_and_grace_period`)

**Verification State:**
- **Provider Sandbox & Webhook Reconciliation:** **`SANDBOX_VERIFIED`** (`tests/test_p3_1_payment_sandbox_verification.py` + `tests/test_payment.py` + `tests/test_subscription_lifecycle.py` + `tests/test_p2_revenue_engine.py`)
- **Live Low-Value Charge, Refund, & Merchant Settlement:** **`NOT_TESTED`** (no live money movement executed without explicit owner authorization)

---

## 1. Capture vs Merchant Settlement Separation

P3.1 explicitly enforces that **buyer payment capture (`CAPTURED_PENDING_SETTLEMENT`) is NOT treated as settled merchant payout (`SETTLED_TO_MERCHANT`)**:

| Event / Stage | Invoice `metadata_json.settlement_status` | `payout_settled` Flag | P2 Reconciliation `metadata_json.settlement_status` | API `settlement_classification` |
|---|---|---|---|---|
| Razorpay `payment.captured` / PayPal `PAYMENT.CAPTURE.COMPLETED` or `PAYMENT.SALE.COMPLETED` | `CAPTURED_PENDING_SETTLEMENT` | `false` | `CAPTURED_PENDING_SETTLEMENT` | `CAPTURED_PENDING_SETTLEMENT` |
| Razorpay `settlement.processed` / PayPal `PAYMENT.PAYOUTS-ITEM.SUCCEEDED` | `SETTLED_TO_MERCHANT` | `true` | `SETTLED_TO_MERCHANT` | `SETTLED_TO_MERCHANT` |
| Payment Failure (`payment.failed` / `PAYMENT.CAPTURE.DENIED`) | `PAYMENT_FAILED` | `false` | Reconciled to `FAILED` via `record_payment_failure_or_refund` | `PAYMENT_FAILED` |
| Partial Refund (`< 99%` cumulative) | `PARTIALLY_REFUNDED` | preserves org paid tier | Remains paid unless cumulative `>= 99%` | `PARTIALLY_REFUNDED` |
| Full Cumulative Refund (`>= 99%`) | `REFUND_COMPLETED` / `REFUND_INITIATED` | `org.tier = "free"`, capabilities revoked | Reconciled to `REFUNDED` & engagement revoked | `REFUND_COMPLETED` / `REFUND_INITIATED` |

Additionally, `RazorpayProvider.fetch_settlement(settlement_id)` (`/v1/settlements/{id}`) and `PayPalProvider.fetch_payout_batch(payout_batch_id)` (`/v1/payments/payouts/{id}`) query provider settlement/payout endpoints independently of checkout capture.

---

## 2. Sandbox Matrix Verified (`tests/test_p3_1_payment_sandbox_verification.py`)

All 6 dedicated P3.1 payment verification tests passed alongside existing payment/lifecycle tests:

1. **`test_razorpay_sandbox_order_capture_refund_and_settlement_api`** — Verifies `/v1/orders` minor-unit creation, `/v1/payments/{id}/capture`, partial `/v1/payments/{id}/refund`, and `/v1/settlements/{id}` fetch via `MockTransport`.
2. **`test_paypal_sandbox_order_capture_refund_and_payout_api`** — Verifies OAuth client-credentials token fetch (`api-m.sandbox.paypal.com`), `/v2/checkout/orders` (`CAPTURE` intent), `/capture`, partial `/refund`, and `/v1/payments/payouts/{id}`.
3. **`test_razorpay_webhook_capture_settlement_partial_full_refund_and_idempotency`** — Verifies unknown header (`400`), bad HMAC (`401`), signed capture -> `CAPTURED_PENDING_SETTLEMENT` (`payout_settled: false`), duplicate replay idempotency (`status: "duplicate"`, single invoice/webhook row), `settlement.processed` -> `SETTLED_TO_MERCHANT` (`payout_settled: true`), first `50%` refund (`partially_refunded`, paid tier kept), and second `50%` cumulative refund -> `refunded` + `free` tier downgrade + capability revocation + P2 `REFUNDED`.
4. **`test_paypal_webhook_signature_capture_settlement_and_major_unit_refund`** — Verifies PayPal `/v1/notifications/verify-webhook-signature` `FAILURE` (`401`) vs `SUCCESS` (`200`), capture vs `PAYMENT.PAYOUTS-ITEM.SUCCEEDED`, and major-unit USD string refund (`"14.50"` -> `1450.0` cents) cumulative revocation.
5. **`test_subscription_renewal_payment_failure_and_cancellation_lifecycle`** — Verifies `subscription.charged` credit replenishment (`lead_credits_used = 0`, `outreach_credits_used = 0`) + P3 `ACTIVE` sync, `invoice.payment_failed` -> `PAST_DUE` grace record, `payment.failed` -> `PAYMENT_FAILED` invoice status, and `subscription.cancelled` -> `CANCELLED` + `free` downgrade.
6. **`test_inspect_payment_provider_config_is_non_secret`** — Confirms non-secret mode detection (`sandbox_test` vs `live`, `credentials_present`, `webhook_secret_present`) without exposing any key or secret strings.

---

## 3. Defects Fixed During Payment Verification

- Removed a duplicate local `from datetime import UTC, datetime` inside `payment_webhook_endpoint` (`app/api/v1/webhooks.py`) that caused `UnboundLocalError` on line 159 when handling subscription status webhooks.
- Unindented `record_payment_failure_or_refund(...)` inside Step 6b of `app/api/v1/webhooks.py` so `refunded`, `disputed`, and `failed` invoices reliably revoke P2 reconciliation records (instead of only running on capture/settlement branches), added `settlement.processed` / `refund.*` mappings to `RazorpayProvider._RAZORPAY_EVENT_MAP`, and set `settlement_classification` on refund webhook responses.

---

## 4. Safe Read-Only Live Configuration Inspection

Using non-secret key presence & prefix inspection against local `.env` and `render.yaml`:
- `.env`: `RAZORPAY_KEY_ID` has prefix `rzp_live_`, `PAYPAL_MODE=live`, and `RAZORPAY_WEBHOOK_SECRET` / `PAYPAL_WEBHOOK_ID` are populated.
- `render.yaml` Blueprint (production web service): sets `PAYMENT_PROVIDER=sovereign_direct`, while staging service sets `PAYMENT_MODE=sandbox` and `ENABLE_EXTERNAL_SIDE_EFFECTS=false`.
- **Live low-value transaction & merchant settlement status:** **`NOT_TESTED`** (no real payment, refund, or payout executed pending explicit owner authorization).
