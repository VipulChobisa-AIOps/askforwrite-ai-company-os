# Security Vulnerability & Dependency Scan Policy

## Objective
To establish automated dependency vulnerability scanning as a strict CI/CD release gate and define a machine-enforced, time-bounded waiver protocol (Issue #19).

## Scanning Tooling & Release Gate
1. **Static Application Security Testing (SAST):**
   - Tool: `bandit`
   - Gate: Release-blocking on High and Medium severity application vulnerabilities (`bandit -r app/ -ll -ii --exclude app/dashboard --skip B101,B311`).
2. **Software Composition Analysis (SCA):**
   - Tool: `pip-audit` enforced by `scripts/check_dependency_vulns.py` against `docs/SECURITY_WAIVERS.json`.
   - Gate: CI upgrades build tooling (`pip`, `setuptools`), installs the production runtime dependency set from `pyproject.toml`, and **fails the build (`exit 1`)** on any unwaived vulnerability or any expired waiver.
   - Artifact: Full JSON report uploaded as `pip-audit-report.json` on every CI run.

## Runtime Vulnerability Remediations Applied (2026-11-23)
- Upgraded `pyproject.toml` minimum safe floors (`cryptography>=46.0.6`, `certifi>=2026.10.19`, `pyasn1>=0.6.5`, `langgraph>=1.0.10,<2`, `pillow>=13.0.0,<14`) rather than waiving fixable runtime CVEs across cryptography, certifi, pyasn1, langgraph/checkpoint/sdk, and pillow.

## Active Time-Bounded Waivers (`docs/SECURITY_WAIVERS.json`)

| Package | Advisory / CVE | Severity | Scope | Owner | Rationale / Compensating Control | Expiry Date |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `pytest` | `PYSEC-2026-1845` | Low | Dev/Test Only | `VipulChobisa-AIOps` | Developer test execution framework excluded from production container build; CI security job scans production runtime dependencies separately. | `2026-12-31` |

Expired waivers automatically fail `scripts/check_dependency_vulns.py`.

## Production Docker Image Security
The production container `Dockerfile` enforces:
- Non-root user `appuser:appgroup`
- Stripped build dependencies (`--no-cache-dir`)
- Explicit runtime-only install without development test harnesses.
