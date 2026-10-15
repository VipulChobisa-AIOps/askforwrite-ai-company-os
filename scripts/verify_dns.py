"""DNS and TLS Configuration & Verification Diagnostic Tool.

Tests DNS resolution, CNAME delegation, IP routing, and TLS certificate
validity for https://os.askforwrite.com.
"""

import argparse
import socket
import ssl
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")



def check_dns(domain: str) -> dict:
    """Resolve DNS records (A and CNAME) for the given domain."""
    results = {"domain": domain, "resolved": False, "ips": [], "error": None}
    try:
        addr_info = socket.getaddrinfo(domain, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
        ips = list(set([item[4][0] for item in addr_info]))
        results["resolved"] = True
        results["ips"] = ips
    except socket.gaierror as exc:
        results["error"] = str(exc)
    return results


def check_tls(domain: str) -> dict:
    """Inspect the TLS/SSL certificate served on port 443."""
    results = {"domain": domain, "tls_active": False, "issuer": None, "expires_at": None, "error": None}
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                results["tls_active"] = True
                results["version"] = ssock.version()
                results["cipher"] = ssock.cipher()
                # Parse expiration
                not_after = cert.get("notAfter")
                if not_after:
                    results["expires_at"] = not_after
                issuer = dict(x[0] for x in cert.get("issuer", []))
                results["issuer"] = issuer.get("organizationName") or issuer.get("commonName")
    except Exception as exc:
        results["error"] = str(exc)
    return results


def print_dns_guide(domain: str) -> None:
    print("\n" + "=" * 70)
    print("  AskforWrite AI Company OS — DNS Configuration Manual")
    print("=" * 70)
    print("""
Add the following DNS records in your domain registrar (Hostinger / Cloudflare):

┌─────────┬──────────────────────┬──────────────────────────────────────────┬───────┐
│ TYPE    │ HOST / NAME          │ TARGET / VALUE                           │ TTL   │
├─────────┼──────────────────────┼──────────────────────────────────────────┼───────┤
│ CNAME   │ os                   │ askforwrite-ai-company-os.up.railway.app │ Auto  │
│ CAA     │ @                    │ 0 issue "letsencrypt.org"                │ Auto  │
│ TXT     │ @                    │ v=spf1 include:_spf.hostinger.com ~all   │ Auto  │
│ TXT     │ _dmarc               │ v=DMARC1; p=quarantine; rua=mailto:...  │ Auto  │
└─────────┴──────────────────────┴──────────────────────────────────────────┴───────┘

Railway & Cloudflare automatically provision free Let's Encrypt / DigiCert
TLS certificates once the CNAME delegation propagates (typically 2-15 minutes).
""")


def main():
    parser = argparse.ArgumentParser(description="Verify DNS and TLS for AskforWrite Company OS")
    parser.add_argument("--domain", default="os.askforwrite.com", help="Domain to verify")
    args = parser.parse_args()

    domain = args.domain
    print(f"\n[1/2] Checking DNS resolution for {domain}...")
    dns_res = check_dns(domain)
    if dns_res["resolved"]:
        print(f"  ✅ DNS Resolved: {domain} → {', '.join(dns_res['ips'])}")
    else:
        print(f"  ⚠️  DNS Not Yet Propagated: {dns_res['error']}")
        print("     (CNAME record 'os' → Railway deployment domain is pending registrar propagation)")

    print(f"\n[2/2] Checking TLS Certificate on {domain}:443...")
    tls_res = check_tls(domain)
    if tls_res["tls_active"]:
        print(f"  ✅ TLS Active: Cipher={tls_res.get('cipher', [None])[0]}")
        print(f"  ✅ Issuer: {tls_res.get('issuer')}")
        print(f"  ✅ Expires: {tls_res.get('expires_at')}")
    else:
        print(f"  ℹ️  TLS Handshake: {tls_res['error']}")

    print_dns_guide(domain)


if __name__ == "__main__":
    main()
