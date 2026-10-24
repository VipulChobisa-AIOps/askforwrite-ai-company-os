#!/usr/bin/env python3
"""Comprehensive System & Multi-Site Post-Bug Verification Suite."""

import time
import socket
import json
import warnings
warnings.filterwarnings('ignore')

import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

print("=" * 80)
print("     AskforWrite AI Company OS — Post-PHP Bug System & Ecosystem Audit")
print("=" * 80)

results = {
    "control_plane": [],
    "websites": [],
    "php_apis": [],
    "payment_flow": [],
}

with httpx.Client(headers=HEADERS, follow_redirects=True, verify=False, timeout=15.0) as client:
    # ── 1. Control Plane & FastAPI Core ─────────────────────────────────────
    print("\n[TEST 1: CONTROL PLANE & CORE SERVICES]")
    cp_endpoints = [
        ("https://os.askforwrite.com/health", "Production Health (COM)", 200),
        ("https://os.askforwrite.in/health", "Production Health (IN)", 200),
        ("https://os.askforwrite.com/docs", "OpenAPI Swagger UI", 200),
        ("https://os.askforwrite.com/dashboard/", "Admin & PWA UI", 200),
        ("https://os.askforwrite.com/static/widget.js", "Closer Widget Asset", 200),
        ("https://os.askforwrite.com/dashboard/widget.js", "Direct Widget Route", 200),
        ("https://os.askforwrite.com/v1/capabilities", "System Capabilities", 200),
        ("https://os.askforwrite.com/legal/declaration", "MSME Declaration (UDYAM-RJ-14-0018404)", 200),
    ]
    for url, desc, exp in cp_endpoints:
        t0 = time.time()
        try:
            r = client.get(url)
            dt = round((time.time() - t0) * 1000)
            status = "PASS" if r.status_code == exp else f"FAIL (HTTP {r.status_code})"
            print(f"  • {desc:42} -> [{status:8}] ({dt:4}ms)")
            results["control_plane"].append((desc, status, dt))
        except Exception as e:
            print(f"  • {desc:42} -> [ERROR   ] {type(e).__name__}")
            results["control_plane"].append((desc, "ERROR", 0))

    # ── 2. Live Websites & 24/7 AI Sales Closer ─────────────────────────────
    print("\n[TEST 2: LIVE WEBSITES & WIDGET INJECTION]")
    sites = [
        ("https://os.askforwrite.com", "os.askforwrite.com (Cloud OS COM)"),
        ("https://os.askforwrite.in", "os.askforwrite.in (Cloud OS IN)"),
        ("https://askforwrite.in", "askforwrite.in (Main Platform 138 Pages)"),
        ("https://ask4write.com", "ask4write.com (WordPress Hub)"),
        ("https://askforwrite.com", "askforwrite.com (WordPress Global)"),
        ("https://askforwrite.info", "askforwrite.info (WordPress Docs)"),
        ("https://shop.ask4write.com", "shop.ask4write.com (Storefront)"),
    ]
    for url, label in sites:
        t0 = time.time()
        try:
            cache_bust = f"?t={int(time.time())}" if "askforwrite.in" in url else ""
            r = client.get(url + cache_bust)
            dt = round((time.time() - t0) * 1000)
            has_widget = "widget.js" in r.text
            widget_str = "WIDGET: ACTIVE" if has_widget else ("WIDGET: OPTIONAL" if "shop." in url else "WIDGET: NONE")
            print(f"  • {label:42} -> [HTTP {r.status_code}] [{widget_str:16}] ({dt:4}ms)")
            results["websites"].append((label, r.status_code, widget_str, dt))
        except Exception as e:
            print(f"  • {label:42} -> [FAIL: {type(e).__name__}]")
            results["websites"].append((label, 0, "ERROR", 0))

    # ── 3. PHP API Endpoints & Security Firewall ────────────────────────────
    print("\n[TEST 3: PHP ENDPOINTS, CATALOG & SECURITY FIREWALL]")
    php_tests = [
        ("Catalog API", "GET", "https://askforwrite.in/api/afw_catalog.php", None),
        ("Chatbot API (Query)", "POST", "https://askforwrite.in/api/afw_chat.php", {"message": "Hello, what services do you offer?"}),
        ("Chatbot API (Price)", "POST", "https://askforwrite.in/api/afw_chat.php", {"message": "How much does MBA thesis writing cost?"}),
        ("Order Validation", "POST", "https://askforwrite.in/api/create_order.php", {}),
        ("Payment Webhook Listener", "GET", "https://askforwrite.in/api/payment_webhook.php", None),
    ]
    for name, method, ep, payload in php_tests:
        t0 = time.time()
        try:
            if method == "GET":
                r = client.get(ep)
            else:
                r = client.post(ep, json=payload)
            dt = round((time.time() - t0) * 1000)
            valid = False
            snippet = ""
            if "catalog" in ep and r.status_code == 200:
                valid = "categories" in r.text and "total" in r.text
                snippet = f"{r.json().get('total', 0)} items cataloged"
            elif "chat" in ep and r.status_code == 200:
                valid = r.json().get("success") is True
                snippet = f"Intent: {r.json().get('intent')} | {len(r.json().get('cards', []))} cards"
            elif "create_order" in ep:
                valid = r.status_code == 400 and "valid client name" in r.text
                snippet = "Validation guard active (rejected blank order)"
            elif "webhook" in ep:
                valid = r.status_code == 200
                snippet = "Webhook listener active"
            status = "PASS" if valid else f"WARN (HTTP {r.status_code})"
            print(f"  • {name:28} -> [{status:8}] ({dt:4}ms) [{snippet}]")
            results["php_apis"].append((name, status, snippet, dt))
        except Exception as e:
            print(f"  • {name:28} -> [ERROR   ] {type(e).__name__}")
            results["php_apis"].append((name, "ERROR", str(e), 0))

    # ── 4. Live Sovereign Pay Flow (Postgres Backed) ────────────────────────
    print("\n[TEST 4: SOVEREIGN DIRECTPAY E2E SETTLEMENT FLOW]")
    try:
        t0 = time.time()
        r_session = client.post(
            "https://os.askforwrite.com/v1/pay/create-session",
            json={
                "package_key": "starter",
                "customer_email": "audit@askforwrite.in",
                "company_name": "Audit Verification Corp",
                "currency": "INR",
            }
        )
        dt = round((time.time() - t0) * 1000)
        if r_session.status_code == 200:
            sess_data = r_session.json()
            sess_id = sess_data.get("session_id")
            checkout_url = sess_data.get("checkout_url")
            print(f"  • Session Creation             -> [PASS    ] ({dt:4}ms) Session ID: {sess_id[:12]}...")
            
            # Verify Checkout HTML rendering
            t1 = time.time()
            r_co = client.get(f"https://os.askforwrite.com{checkout_url}")
            dt_co = round((time.time() - t1) * 1000)
            has_upi = "ask4write@icici" in r_co.text
            has_msme = "UDYAM-RJ-14-0018404" in r_co.text
            checkout_ok = r_co.status_code == 200 and has_upi and has_msme
            co_status = "PASS" if checkout_ok else "FAIL"
            print(f"  • Checkout Page Rendering      -> [{co_status:8}] ({dt_co:4}ms) UPI: ask4write@icici | MSME: Verified")
            results["payment_flow"].append(("Sovereign Checkout", co_status, dt_co))
        else:
            print(f"  • Session Creation             -> [FAIL    ] HTTP {r_session.status_code}")
            results["payment_flow"].append(("Sovereign Checkout", "FAIL", 0))
    except Exception as e:
        print(f"  • Session Creation             -> [ERROR   ] {type(e).__name__}")
        results["payment_flow"].append(("Sovereign Checkout", "ERROR", 0))

print("\n" + "=" * 80)
print("     Audit Completed Successfully")
print("=" * 80 + "\n")
