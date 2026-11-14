# P8 Developer SDK & Plugin Manifest Specification

**Version:** 1.0  
**Applies To:** AskforWrite AI Company OS — `/v1/p8/marketplace/*`

---

## 1. Canonical Plugin Manifest Format

Every package submitted via `POST /v1/p8/marketplace/listings` generates a canonical JSON manifest using deterministic compact serialization (`sort_keys=True`, separators `(",", ":")`):

```json
{
  "developer_id": "<uuid>",
  "endpoint_url": "https://hooks.partner-example.in/events",
  "listing_slug": "tally-gst-sync",
  "name": "Tally GST Reconciliation Connector",
  "package_type": "CONNECTOR_ADAPTER",
  "permissions": ["read_metrics", "stage_content"],
  "version": "1.0.0"
}
```

### Supported `package_type` Values
- `AGENT_PLUGIN`
- `CONNECTOR_ADAPTER`
- `WORKFLOW_PACK`

---

## 2. Cryptographic Signing & Verification Flow

1. Server validates developer KYB status (`VERIFIED`), claim safety (`check_gtm_copy_safety`), endpoint SSRF safety (`validate_external_url`), and `commission_bps` bounds (`500`–`3000`, i.e., `5%`–`30%`).
2. Canonical JSON is hashed with **SHA-256** (`manifest_sha256`).
3. Digest is signed using the platform **ECDSA NIST P-256** key via `app.security.ecdsa_pki.sign_block` (`ecdsa_signature_hex` + `signing_public_key_pem`).
4. Anyone can verify integrity before install via `GET /v1/p8/marketplace/listings/{listing_id}/verify-signature`, returning `sha256_match`, `ecdsa_valid`, and `verified`.
5. Any mutation to `manifest_json` invalidates `sha256_match` and blocks `install_marketplace_listing` with `403`.

---

## 3. Permission Allowlist Contract

Packages may request ONLY least-privilege scopes defined in `ALLOWED_PLUGIN_PERMISSIONS`:

| Permission Scope | Capability Granted |
| :--- | :--- |
| `read_icps` | Read tenant ICP definitions (`GET` scope only) |
| `read_metrics` | Read non-secret operational telemetry & funnel counts |
| `stage_content` | Stage draft assets/recommendations requiring HITL approval |
| `run_sandbox_diagnostics` | Execute isolated diagnostic checks under `SIMULATION` / `SANDBOX` |
| `emit_webhook` | Emit signed outbound payloads via SSRF-checked HTTPS URLs |

Wildcards (`*`), cross-tenant scopes, raw database access, and plaintext secret exports are rejected with `422`.

---

## 4. Tenant Credential Isolation & Billing Hooks

- Installers pass runtime secrets via `POST /v1/p8/marketplace/installs` (`secrets_payload`).
- The gateway converts each value to a masked preview (`••••<last4>`) and an org-bound digest `SHA-256("<org_id>:<key>:<value>")` inside `secret_digests_json`.
- Plaintext secret values are never persisted to `p8_tenant_installs` or returned by `/v1/p8/marketplace/installs`.
- Commission ledger entries (`POST /v1/p8/marketplace/revenue-share`) require explicit `evidence_status` (`SANDBOX` or `ACTUAL`) and calculate exact `platform_commission_inr` and `developer_payout_inr` splits from `commission_bps`.
