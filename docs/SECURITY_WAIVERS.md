# Security Vulnerability & Dependency Scan Policy

## Objective
To establish automated dependency vulnerability scanning as a strict CI/CD release gate and define a documented, time-bounded waiver protocol for low-risk, non-runtime dependencies (Issue #19).

## Scanning Tooling & Release Gate
1. **Static Application Security Testing (SAST)**:
   - Tool: `bandit`
   - Gate: Release-blocking on High and Medium severity application vulnerabilities (`bandit -r app/ -ll -ii`).
2. **Software Composition Analysis (SCA)**:
   - Tool: `pip-audit` / `safety`
   - Gate: Fails on any High/Critical vulnerability detected in production runtime dependencies (`pyproject.toml` runtime dependencies).

## Documented Waivers & Triage

| Package | Version | Advisory / CVE | Severity | Scope | Rationale / Mitigation | Expiry Date |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `pip` / `setuptools` | CI runner default | GHSA-xmj3-9gf7-h52w | Medium | CI Environment Only | Build-time and test harness dependency inside ephemeral GitHub Actions container. Not included in production Docker image (`python:3.12-slim` runs with non-root production user). | 2026-12-31 |
| `pytest` | 8.4.2 | PYSEC-2026-1845 | Low | Test Suite Only | Developer test execution framework; excluded from production deployment and container build. | 2026-12-31 |

## Production Docker Image Security
The production container `Dockerfile` enforces:
- Non-root user `appuser:appgroup`
- Stripped build dependencies (`--no-cache-dir`)
- Explicit virtual environment boundary without development test harnesses.

