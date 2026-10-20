#!/usr/bin/env python3
"""AskforWrite AI Company OS — Live Domain & Cloud Verification Tool.

Tests DNS resolution, SSL handshake, backend /health, and PWA assets for os.askforwrite.com.
"""

from __future__ import annotations

import socket
import sys
import httpx

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DOMAIN = "os.askforwrite.com"
HOSTINGER_PARKING_IP = "31.170.161.131"


def check_domain():
    print("\n" + "=" * 70)
    print(f" 🌐 Verifying Live Cloud & DNS Status for https://{DOMAIN}")
    print("=" * 70)

    # 1. DNS Resolution
    print("\n[1/4] Checking DNS Resolution...")
    try:
        ip = socket.gethostbyname(DOMAIN)
        print(f"  • Resolved IP: {ip}")
        if ip == HOSTINGER_PARKING_IP:
            print(f"  ⚠️ Warning: {DOMAIN} is still pointing to Hostinger Parking ({HOSTINGER_PARKING_IP}).")
            print("     Update your CNAME record in Hostinger hPanel to your Render service address.")
        else:
            print(f"  ✅ {DOMAIN} is pointing to cloud target ({ip}).")
    except Exception as exc:
        print(f"  ❌ DNS lookup failed: {exc}")
        return

    # 2. SSL and HTTP Root
    print("\n[2/4] Testing HTTPS Connection...")
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        try:
            r = client.get(f"https://{DOMAIN}/")
            print(f"  • Root https://{DOMAIN}/ Status: HTTP {r.status_code}")
            if "Hostinger" in r.text or "parked" in r.text.lower():
                print("  ℹ️ Current Response: Hostinger Default Parking Page.")
            else:
                print("  ✅ Custom response received.")
        except Exception as exc:
            print(f"  ❌ HTTPS request failed: {exc}")

        # 3. Health Endpoint
        print("\n[3/4] Checking AI OS Health Check (/health)...")
        try:
            r_health = client.get(f"https://{DOMAIN}/health")
            if r_health.status_code == 200:
                print(f"  ✅ Health Check: HTTP 200 OK — {r_health.text[:100]}")
            else:
                print(f"  ⚠️ Health Check: HTTP {r_health.status_code} (Not reachable yet)")
        except Exception as exc:
            print(f"  ⚠️ Health endpoint test: {exc}")

        # 4. PWA Dashboard Check
        print("\n[4/4] Checking PWA Portal (/dashboard/)...")
        try:
            r_dash = client.get(f"https://{DOMAIN}/dashboard/")
            r_manifest = client.get(f"https://{DOMAIN}/dashboard/manifest.json")
            if r_dash.status_code == 200 and r_manifest.status_code == 200:
                print("  ✅ PWA Portal & Web App Manifest: ONLINE & INSTALLABLE!")
            else:
                print(f"  ⚠️ Dashboard: HTTP {r_dash.status_code}, Manifest: HTTP {r_manifest.status_code}")
        except Exception as exc:
            print(f"  ⚠️ Dashboard test: {exc}")

    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    check_domain()
