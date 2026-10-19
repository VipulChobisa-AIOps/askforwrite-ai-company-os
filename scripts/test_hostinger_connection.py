#!/usr/bin/env python3
"""Hostinger & 4-Site WordPress Network Connectivity Diagnostics.

Verifies DNS, SSL, WordPress REST API (/wp-json/), GEO/AIO (/llms.txt),
and REST authenticated publishing for:
1. askforwrite.in
2. theaiscene.in
3. careersathi.in
4. edutechguide.in
"""

from __future__ import annotations

import os
import sys
import urllib.parse
from dotenv import load_dotenv
import httpx

load_dotenv()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

SITES = [
    {
        "id": "askforwrite",
        "name": "AskforWrite Main Platform",
        "url": "https://askforwrite.in",
    },
    {
        "id": "theaiscene",
        "name": "The AI Scene India",
        "url": "https://theaiscene.in",
    },
    {
        "id": "careersathi",
        "name": "Career Sathi EdTech",
        "url": "https://careersathi.in",
    },
    {
        "id": "edutechguide",
        "name": "EduTech Guide Platform",
        "url": "https://edutechguide.in",
    },
]


def test_site(client: httpx.Client, site: dict[str, str]) -> dict[str, object]:
    url = site["url"]
    results = {
        "site": site["name"],
        "url": url,
        "online": False,
        "status_code": None,
        "rest_api_active": False,
        "llms_txt_active": False,
        "widget_detected": False,
        "auth_verified": False,
        "notes": [],
    }

    # 1. Base Homepage Reachability
    try:
        resp = client.get(url, follow_redirects=True, timeout=8.0)
        results["status_code"] = resp.status_code
        if resp.status_code == 200:
            results["online"] = True
            body = resp.text
            if "widget.js" in body:
                results["widget_detected"] = True
            else:
                results["notes"].append("Widget not detected yet (Upload askforwrite-ai-os-bridge.zip)")
        else:
            results["notes"].append(f"HTTP {resp.status_code}")
    except Exception as exc:
        results["notes"].append(f"Connection error: {type(exc).__name__}")
        return results

    # 2. WordPress REST API Discovery
    try:
        rest_resp = client.get(f"{url}/wp-json/", follow_redirects=True, timeout=8.0)
        if rest_resp.status_code == 200:
            results["rest_api_active"] = True
        else:
            results["notes"].append(f"REST API /wp-json/ returned {rest_resp.status_code}")
    except Exception as exc:
        results["notes"].append(f"REST API ping failed: {type(exc).__name__}")

    # 3. /llms.txt 2026 AI Crawler Manifest
    try:
        llm_resp = client.get(f"{url}/llms.txt", follow_redirects=True, timeout=8.0)
        if llm_resp.status_code == 200 and "llms.txt" in llm_resp.text.lower():
            results["llms_txt_active"] = True
        else:
            results["notes"].append("/llms.txt inactive (Activate Bridge Plugin)")
    except Exception:
        results["notes"].append("/llms.txt route timed out")

    # 4. Authenticated REST check (if credentials match this domain)
    wp_site_url = os.getenv("WP_SITE_URL", "")
    wp_user = os.getenv("WP_USERNAME", "")
    wp_pass = os.getenv("WP_APP_PASSWORD", "")

    if wp_site_url and wp_user and wp_pass:
        parsed_current = urllib.parse.urlparse(url).netloc.lower()
        parsed_target = urllib.parse.urlparse(wp_site_url).netloc.lower()
        if parsed_current == parsed_target:
            try:
                auth_resp = client.get(
                    f"{url}/wp-json/wp/v2/users/me",
                    auth=(wp_user, wp_pass),
                    follow_redirects=True,
                    timeout=8.0,
                )
                if auth_resp.status_code == 200:
                    results["auth_verified"] = True
                else:
                    results["notes"].append(f"WP Auth failed (HTTP {auth_resp.status_code})")
            except Exception as e:
                results["notes"].append(f"WP Auth error: {type(e).__name__}")

    return results


def main() -> int:
    print("\n" + "═" * 78)
    print(" 🚀 AskforWrite AI Company OS — Hostinger 4-Site Network Diagnostic")
    print("═" * 78)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AskforWriteCompanyOS/1.0",
        "Accept": "*/*",
    }

    all_online = True
    with httpx.Client(headers=headers, verify=True) as client:
        for site in SITES:
            print(f"\nScanning: {site['name']} ({site['url']})...")
            res = test_site(client, site)

            status_icon = "✅ ONLINE" if res["online"] else "❌ OFFLINE"
            rest_icon = "✅ ACTIVE" if res["rest_api_active"] else "⚠️ INACTIVE"
            llms_icon = "✅ SERVED" if res["llms_txt_active"] else "⏳ PENDING PLUGIN"
            widget_icon = "✅ EMBEDDED" if res["widget_detected"] else "⏳ PENDING PLUGIN"

            print(f"  • Status:       {status_icon} (HTTP {res['status_code']})")
            print(f"  • REST API:     {rest_icon}")
            print(f"  • /llms.txt:    {llms_icon}")
            print(f"  • Sales Closer: {widget_icon}")

            if res["auth_verified"]:
                print("  • WP REST Auth: ✅ VERIFIED (Application Password Active)")

            if res["notes"]:
                print(f"  • Diagnostics:  {'; '.join(res['notes'])}")

            if not res["online"]:
                all_online = False

    print("\n" + "═" * 78)
    if all_online:
        print(" 🎉 Network Scan Complete: WordPress hosts are reachable and responsive.")
    else:
        print(" ⚠️  Some properties require DNS propagation or plugin upload.")
    print("═" * 78 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
