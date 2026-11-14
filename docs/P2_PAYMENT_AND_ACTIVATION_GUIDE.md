# P2 Payment Settlement & Customer Activation Guide

---

## 1. Non-Negotiable Settlement Principle

Creating a payment link or checkout session **never** marks a proposal accepted for billing settlement, **never** transitions a lead to `WON`, **never** increments verified revenue KPIs, and **never** activates customer entitlements.

Only two verified settlement paths trigger activation:

1. **Razorpay / PayPal HMAC-Verified Webhook (`POST /v1/webhooks/payment`):**
   - Signature verified via `RazorpayProvider.verify_webhook` (`X-Razorpay-Signature` HMAC-SHA256 against `RAZORPAY_WEBHOOK_SECRET` / `RAZORPAY_KEY_SECRET`) or PayPal verification.
   - `provisioning.auto_provision_tenant_on_payment()` validates SKU existence, currency (`INR`/`USD`), and paid amount >= 95% of catalog price before creating `OrganizationRecord`, `UserRecord`, and `InvoiceRecord`.
   - Calls `p2_proposal_settlement.reconcile_verified_payment()`.

2. **AFW DirectPay Verified Proof + Owner Confirmation (`/v1/pay/{session_id}/verify` -> `/v1/pay/{session_id}/confirm-owner`):**
   - Buyer submits UPI UTR / bank wire ref / USDC tx hash via `POST /v1/pay/{session_id}/verify` (moves session to `AWAITING_OWNER_CONFIRMATION`).
   - Owner reconciles funds in bank account and confirms via `POST /v1/pay/{session_id}/confirm-owner`.
   - Triggers provisioning + NIST P-256 TrustBlock seal + `reconcile_verified_payment()`.

---

## 2. Idempotency, Underpayment Protection & Retry Queue

- **Replay Guard:** `P2PaymentReconciliationRecord.provider_event_id` deduplicates repeated webhooks; already-activated events return `status: "ALREADY_ACTIVATED"` without duplicate orgs, invoices, or engagements.
- **Withheld / Underpaid Events:** If provisioning returns `unknown_package_withheld`, `unsupported_currency_withheld`, or `underpaid_withheld`, reconciliation enters `RETRY_NEEDED` (`customer_activated: False`) and preserves honest failure diagnostics.
- **Deterministic Retry:** `POST /v1/commercial/reconciliation/{reconciliation_id}/retry` re-checks `received_amount >= expected_amount * 0.95` before attempting provisioning, returning `RETRY_BLOCKED_UNVERIFIED_AMOUNT` if underpaid.

---

## 3. Refund, Chargeback & Dispute Revocation

When a webhook delivers a verified full refund (`refund.processed` / `REFUND_COMPLETED`), chargeback, or dispute (`record_payment_failure_or_refund()`):

1. Linked `P2CustomerEngagementRecord` entries transition immediately to `CANCELLED_OR_REFUNDED` with `entitlements_json = []` and `assigned_modules_json = []`.
2. Customer `OrganizationRecord.tier` reverts to `free` and `metadata_json["entitled_capabilities"]` clears to `[]`.
3. `P2ProspectDossierRecord` updates to `payment_status = "REFUNDED" | "DISPUTED"`, `activation_status = "REVOKED"`, `pipeline_status = "LOST"`.
4. Subsequent calls to `execute_pilot_delivery` or `complete_engagement_delivery` fail cleanly (`HTTP 422`).
