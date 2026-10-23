import httpx
import time
import socket
import ssl
import json
import warnings
warnings.filterwarnings('ignore')

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

print("=" * 80)
print("     AskforWrite AI Company OS — Comprehensive System-Wide Audit")
print("=" * 80)

# 1. Control Plane & Render Endpoints
print("\n[SECTION 1: CONTROL PLANE & RENDER DEPLOYMENT]")
control_plane_endpoints = [
    ("https://os.askforwrite.com/health", "Production Healthcheck (COM)"),
    ("https://os.askforwrite.in/health", "Production Healthcheck (IN)"),
    ("https://os.askforwrite.com/docs", "FastAPI Swagger Docs"),
    ("https://os.askforwrite.com/dashboard/", "Admin & Company OS Dashboard"),
    ("https://os.askforwrite.com/static/widget.js", "Closer Widget Asset"),
    ("https://os.askforwrite.com/dashboard/widget.js", "Direct Widget Route"),
    ("https://os.askforwrite.com/v1/pay/checkout?package=growth_all_in_one", "AFW DirectPay Sovereign Checkout")
]

with httpx.Client(headers=headers, follow_redirects=True, verify=False, timeout=12.0) as client:
    for url, desc in control_plane_endpoints:
        t0 = time.time()
        try:
            r = client.get(url)
            elapsed = round((time.time() - t0) * 1000)
            status_symbol = "OK" if r.status_code in (200, 307, 308) else f"HTTP {r.status_code}"
            print(f"  • {desc:36} -> [{status_symbol:8}] ({elapsed:4}ms) {url}")
            if "health" in url and r.status_code == 200:
                print(f"    Payload: {r.text.strip()}")
        except Exception as e:
            print(f"  • {desc:36} -> [FAILED  ] {type(e).__name__} ({url})")

# 2. Ecosystem Sites & Widget Embed Verification
print("\n[SECTION 2: ALL LIVE SITES & WIDGET INTEGRATION]")
sites = [
    ("https://askforwrite.in", "AskforWrite Main Platform (IN - 138 Pages)"),
    ("https://ask4write.com", "Ask4Write Brand & Commerce Hub"),
    ("https://askforwrite.com", "AskforWrite Global Hub"),
    ("https://askforwrite.info", "AskforWrite Knowledge Base"),
    ("https://shop.ask4write.com", "Ask4Write Paper Store"),
    ("https://os.askforwrite.in", "AskforWrite Company OS (IN)"),
    ("https://os.askforwrite.com", "AskforWrite Company OS (COM)")
]

with httpx.Client(headers=headers, follow_redirects=True, verify=False, timeout=12.0) as client:
    for url, label in sites:
        t0 = time.time()
        try:
            r = client.get(url + ("?t=" + str(time.time()) if "askforwrite.in" == url.split("//")[1] else ""))
            elapsed = round((time.time() - t0) * 1000)
            has_widget = "widget.js" in r.text
            status = f"HTTP {r.status_code}"
            widget_status = "WIDGET: ACTIVE" if has_widget else ("WIDGET: OPTIONAL" if "shop." in url else "WIDGET: MISSING")
            print(f"  • {label:42} -> [{status:8}] [{widget_status:16}] ({elapsed:4}ms)")
        except Exception as e:
            print(f"  • {label:42} -> [FAILED  ] {type(e).__name__}")

# 3. DNS Verification
print("\n[SECTION 3: DNS ROUTING & PROPAGATION]")
dns_targets = [
    "os.askforwrite.in",
    "os.askforwrite.com",
    "askforwrite.in",
    "ask4write.com",
    "askforwrite.com",
    "askforwrite.info",
    "shop.ask4write.com"
]

for host in dns_targets:
    try:
        ip = socket.gethostbyname(host)
        print(f"  • {host:24} -> IP: {ip}")
    except Exception as e:
        print(f"  • {host:24} -> RESOLUTION ERROR: {e}")

print("\n" + "=" * 80)
print("     Audit Complete")
print("=" * 80 + "\n")
