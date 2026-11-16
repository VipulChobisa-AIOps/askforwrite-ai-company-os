# AskforWrite AI Company OS — P8 Marketplace Security & Package Governance Report

**Branch:** `fix/infra-remediation-from-11b466e` (based on `11b466e`)
**Execution Context:** Pre-Release P8 Marketplace Security & Durable PKI Audit (R2 / R4)
**Verification Date:** 2026-11-16
**Primary Modules:** `app/api/v1/p8_marketplace.py`, `app/services/p8_marketplace.py`, `app/security/ecdsa_pki.py`
**Primary Test Suites:** `tests/test_security_hardening_p8_marketplace.py` (3 tests), `tests/test_p8_marketplace_and_scorecard.py` (3 tests), `tests/test_security_hardening_cross_record_fk.py` (4 tests), `tests/test_infra_remediation_readiness.py` (durable key + rotation verification)
**Executable Plugin Status:** **PERMANENTLY DISABLED (Declarative Manifests Only)**
**Overall P8 Status:** **VERIFIED (`LOCAL_VERIFIED` / `STAGING_VERIFIED` on Neon `afw_staging` & `afw_restore_drill`)**

---

## 1. Executive Summary

This report establishes the security verification, cryptographic trust architecture, and multi-tenant isolation perimeters for the P8 Marketplace Ecosystem in AskforWrite AI Company OS.

Key protections verified:
1. **Developer KYB & Ownership Enforcement:** Developers must bind to an active organization. Cross-organization developer spoofing is rejected with `403 Forbidden`.
2. **Deterministic Cryptographic Signing:** Package manifests are serialized into canonical, deterministic JSON and cryptographically signed using ECDSA NIST P-256 and SHA-256. Listing verification checks both canonical manifest hash integrity and public key pinning (`public_key_pinned`), detecting rogue key replacement or manifest tampering.
3. **Tenant Secret Isolation:** Configuration secrets provided during plugin installation are converted into tenant-scoped SHA-256 digests (`secret_digests_json`) and masked preview tails (`••••last4`). Raw secrets are never stored in the database or returned in API responses.
4. **Third-Party Code Execution Disabled:** The marketplace strictly prohibits the runtime execution of third-party executable code. All packages are declarative metadata manifests, webhook endpoints, and permission scopes.
5. **Install Revocation & Zero Leakage:** Revoking an installation immediately purges stored secret digests, seals an immutable event to the `TrustChain`, and blocks subsequent revenue share calculations.

---

## 2. Developer KYB & Multi-Tenant Privacy

### 2.1 Developer Profile Registration
In `app/services/p8_marketplace.py:114-150`:
- `register_developer_profile` requires an existing `OrganizationRecord`.
- If the organization is suspended or marked inactive (`org.is_active == False`), registration fails with `403 Forbidden` (`"Organization account is inactive or suspended"`).
- Developer status defaults to `PENDING` until platform operator KYB approval. Unapproved or suspended developers cannot publish listings or receive payouts.

### 2.2 PII Redaction for Public & Cross-Tenant Callers
When developer profiles or marketplace listings are retrieved:
- **Contact Email:** Masked for non-operators (`u***@domain.com`).
- **Tax / GST / Account Data:** Stripped completely (`tax_or_gst_id = None`, `payout_account_masked = None`) for all cross-tenant callers.
- **Draft Privacy:** Draft or pending-review listings are completely hidden from other organizations (`PermissionError` -> `403`/`404`), even when callers supply `?published_only=false`.
- **Administrative Fields Redacted:** Public listing responses omit internal `ecdsa_signature_hex`, `review_notes`, and `approved_by`.

---

## 3. Cryptographic Signing & Node Key Pinning

```
┌────────────────────────────────────────────────────────────────────────┐
│                   CANONICAL MANIFEST SIGNING FLOW                      │
│                                                                        │
│   Listing Manifest Data                                                │
│   ├── name, slug, version, package_type                                │
│   ├── permissions, external_endpoints                                  │
│   └── pricing_tier, author_developer_id                                │
│                     │                                                  │
│                     ▼                                                  │
│   _canonical_manifest() (sort_keys=True, separators=(",", ":"))        │
│                     │                                                  │
│                     ├──────────────────────────┐                       │
│                     ▼                          ▼                       │
│             SHA-256 Hash Digest           ECDSA NIST P-256 Sign        │
│             (manifest_canonical_hash)     (ecdsa_signature_hex)        │
│                     │                          │                       │
│                     └──────────┬───────────────┘                       │
│                                │                                       │
│                                ▼                                       │
│        Pinned to Listing: public_key_pinned + signature                │
└────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Canonical Manifest Serialization
In `app/services/p8_marketplace.py:56-80`:
- Manifests are normalized into compact canonical JSON with sorted keys and minimal whitespace.
- Any mutation of listing metadata (e.g., name, permissions, pricing, or webhook URLs) after publication causes the computed SHA-256 hash to diverge, failing signature verification.

### 3.2 Anti-Tamper, Rogue Key Rejection & Zero-Downtime Rotation (`verify_listing_signature`)
`verify_listing_signature` enforces durable trusted-keyring cryptographic checks:
1. **Canonical Hash Match:** Confirms that the current listing metadata reproduces the exact `manifest_canonical_hash`.
2. **Trusted Node Keyring Pinning (`is_trusted_node_public_key`):** Validates `listing.signing_public_key_pem` against the active node public key (`TRUST_ENGINE_PRIVATE_KEY_PEM` or persistent `node_public_key.pem`) **plus** explicitly configured/archived retired node public keys (`TRUST_ENGINE_RETIRED_PUBLIC_KEYS_PEM` / `retired_public_keys.json`).
   - Attacker-supplied rogue keypairs (`rogue_pub`) remain rejected (`public_key_pinned = False`, `verified = False`).
   - Legitimate `rotate_node_keypair()` preserves continuous verification for listings published prior to rotation while signing new listings with the newly active `kid` (`LOCAL_VERIFIED`, `STAGING_VERIFIED`).
3. **Draft Gating:** Unauthenticated or unrelated tenants attempting to run `verify-signature` on unpublished draft listings are rejected with `403 Forbidden`.

---

## 4. Installation Security, Secret Masking & Revocation

### 4.1 Secret Isolation Model
When a tenant installs a marketplace listing via `POST /v1/p8/marketplace/listings/{id}/installs`:
- The request accepts configuration secrets in `secrets_payload` (e.g. third-party CRM API keys).
- In `app/services/p8_marketplace.py:468-538`, each secret is processed:
  ```python
  digest = hashlib.sha256(f"{target_org_id}:{k}:{v}".encode()).hexdigest()
  secret_digests[k] = digest
  masked_previews[k] = f"••••{v[-4:]}" if len(v) >= 4 else "••••"
  ```
- Stored records contain **only** `secret_digests_json` and `masked_previews`. Raw secret values are discarded immediately after hashing.
- API responses for installs display only masked tails (`••••last4`) and never expose the SHA-256 digest or plaintext.

### 4.2 Installation Revocation Protocol
When a tenant revokes an install via `POST /v1/p8/marketplace/installs/{id}/revoke`:
1. The endpoint validates tenant ownership (`install.org_id == principal.org_id`).
2. Status transitions to `REVOKED`.
3. Secret digests are permanently erased: `secret_digests_json = {}`.
4. A revocation trust block is cryptographically sealed to `TrustChain`.
5. Future attempts to record revenue share or trigger the install are rejected with `403 Forbidden` (`"Cannot record revenue share for an inactive or revoked installation"`).

---

## 5. Review Governance & Anti-Abuse Controls

1. **Verified Purchase / Install Required:** Non-installers attempting to review a listing are rejected with `403 Forbidden` (`"Only organizations with an active installation may review this listing"`).
2. **Duplicate Review Protection:** Submitting a second review for the same installation returns `409 Conflict` (`"Review already exists for this installation"`).
3. **GTM Copy Safety:** Reviews pass through `check_gtm_copy_safety`, rejecting fabricated ROI claims or unverified claims with `422 Unprocessable Entity`.
4. **Public Review Redaction:** When public users view reviews, internal operational fields are redacted: `abuse_reason=None`, `abuse_flagged=False`, `created_by=None`, `org_id=None`.

---

## 6. Permanent Disabling of Executable Third-Party Code

To guarantee total platform safety and prevent remote code execution (RCE):
- `PACKAGE_TYPES` supports `"AGENT_PLUGIN"`, `"CONNECTOR_ADAPTER"`, and `"WORKFLOW_PACK"`.
- However, **no executable code interpreter or plugin dynamic loader exists** in `app/services/registry.py` or elsewhere in the codebase.
- Third-party packages function exclusively as **declarative manifests** specifying REST webhook targets, JSON schema parameter specifications, and RBAC permission scopes.
- All agent execution in the AskforWrite OS runs strictly through first-party built-in agents defined in `AGENT_REGISTRY`.

---

## 7. Database Foreign Key Constraints (P8)

Migration `o5d0e1f2a3b4` and `tests/test_security_hardening_cross_record_fk.py` verify database-level referential integrity:
- `p8_marketplace_listings.developer_id -> p8_developer_profiles.id` (`ON DELETE RESTRICT`): Prevents deleting a developer profile while active listings exist.
- `p8_tenant_installs.listing_id -> p8_marketplace_listings.id` (`ON DELETE RESTRICT`): Prevents deleting a marketplace listing while active tenant installations exist.
- `p8_marketplace_reviews.listing_id -> p8_marketplace_listings.id` (`ON DELETE CASCADE`): Deletes reviews if a listing is removed.
- `p8_marketplace_reviews.install_id -> p8_tenant_installs.id` (`ON DELETE CASCADE`): Deletes reviews if an install is removed.

---

## 8. Verification Evidence & Test Results

```powershell
.\.venv\Scripts\pytest tests/test_security_hardening_p8_marketplace.py tests/test_p8_marketplace_and_scorecard.py tests/test_security_hardening_cross_record_fk.py -v
```

| Test Name | Targeted Verification | Result | Status |
| :--- | :--- | :--- | :--- |
| `test_p8_cross_tenant_developer_ownership_visibility_and_pii_redaction` | Developer ownership, PII redaction & draft privacy | Passed | `LOCAL_VERIFIED` |
| `test_p8_signature_key_pinning_rereview_and_kyb_revocation` | ECDSA signing, key pinning, tampered manifest rejection | Passed | `LOCAL_VERIFIED` |
| `test_p8_reviews_hardening_install_revoke_and_redaction` | Install revocation, secret masking (`••••last4`), review privacy | Passed | `LOCAL_VERIFIED` |
| `test_p8_marketplace_and_scorecard.py` (3 tests) | Marketplace lifecycle & platform manager scorecard gating | Passed | `LOCAL_VERIFIED` |
| `test_db_level_foreign_key_constraints_enforced` | P8 `RESTRICT` and `CASCADE` FK database constraints | Passed | `LOCAL_VERIFIED` |

*Summary:* All **10 marketplace security and referential integrity tests pass cleanly (`LOCAL_VERIFIED`)**.
