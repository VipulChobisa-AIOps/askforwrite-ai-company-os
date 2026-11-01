# Security Policy

## Reporting Security Vulnerabilities

ASKFORWRITE and the **AskforWrite AI Company OS** maintain a zero-tolerance policy for uncoordinated vulnerability disclosure and take all security concerns seriously.

If you discover a vulnerability or security flaw, **please DO NOT create a public issue, pull request, or discussion thread.**

### Responsible Disclosure Channel
- **Email:** [security@askforwrite.in](mailto:security@askforwrite.in)
- **Subject Line:** `[VULNERABILITY REPORT] <Short Description>`
- **Response SLA:** Acknowledgment within 24 hours; initial assessment and triage within 72 hours.
- **Entity Identity:** Formally registered Indian Micro Enterprise under the MSMED Act, 2006 (Udyam Registration: `UDYAM-RJ-14-0018404`).

Please include the following in your report:
1. Description of the vulnerability and its potential impact.
2. Specific endpoints, modules, or services affected.
3. Reproducible step-by-step instructions or proof-of-concept (PoC) payload.
4. Mitigation recommendations (if any).

---

## Supported Versions

Only the latest release on the `main` branch deployed to production (`https://os.askforwrite.com`) is actively maintained and receives security updates.

| Version | Supported |
|---|---|
| `main` (Latest Production) | :white_check_mark: |
| < 0.2.0 | :x: |

---

## Security Architecture & Defenses

AskforWrite AI Company OS implements defense-in-depth:
- **Server-Side Request Forgery (SSRF) Protection:** Strict filtering on domain auditing and scraping preventing connections to loopback (`127.0.0.1`, `localhost`), link-local/cloud metadata (`169.254.169.254`), and RFC 1918 private subnets.
- **Cryptographic Auditability:** ECDSA NIST P-256 Merkle chain block sealing for all sensitive actions.
- **Multi-Tenant Isolation:** Explicit tenant quota attribution and cross-organization access isolation.
- **Static Analysis & SAST:** Automated Bandit and CodeQL scanning in CI/CD.
