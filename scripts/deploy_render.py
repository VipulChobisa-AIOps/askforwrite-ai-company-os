#!/usr/bin/env python3
"""Render.com Automated Blueprint Deployment Script.

Uses Render REST API v1 to deploy VipulChobisa-AIOps/askforwrite-ai-company-os
directly from render.yaml with automated database and web service provisioning.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dotenv import load_dotenv
import httpx

load_dotenv()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

RENDER_API_BASE = "https://api.render.com/v1"
REPO_URL = "https://github.com/VipulChobisa-AIOps/askforwrite-ai-company-os"
BRANCH = "main"


def get_owner_id(client: httpx.Client) -> tuple[str, str]:
    """Retrieve the Render account owner / team ID."""
    resp = client.get(f"{RENDER_API_BASE}/owners")
    if resp.status_code != 200:
        raise ValueError(f"Failed to fetch Render account: HTTP {resp.status_code} - {resp.text}")
    owners = resp.json()
    if not owners:
        raise ValueError("No Render account owner or team found for this API token.")
    first = owners[0].get("owner", owners[0])
    return first.get("id"), first.get("name", "Vipul")


def deploy_blueprint(api_key: str) -> None:
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "AskforWrite-Deployment/1.0",
    }

    with httpx.Client(headers=headers, timeout=30.0) as client:
        print("\n" + "=" * 70)
        print(" 🚀 AskforWrite AI Company OS — Render 1-Click Cloud Deployment")
        print("=" * 70)

        # 1. Validate credentials & fetch Owner ID
        print("\n[1/4] Authenticating with Render REST API...")
        owner_id, owner_name = get_owner_id(client)
        print(f"  ✅ Authenticated as: {owner_name} (Owner ID: {owner_id})")

        # 2. Check for existing blueprints
        print("\n[2/4] Checking existing blueprints...")
        bp_list_resp = client.get(f"{RENDER_API_BASE}/blueprints")
        existing_bp_id = None
        if bp_list_resp.status_code == 200:
            for item in bp_list_resp.json():
                bp = item.get("blueprint", item)
                if bp.get("repo") == REPO_URL or "askforwrite" in bp.get("name", "").lower():
                    existing_bp_id = bp.get("id")
                    print(f"  ℹ️ Found existing blueprint: {bp.get('name')} (ID: {existing_bp_id})")
                    break

        # 3. Create or Sync Blueprint
        if existing_bp_id:
            print(f"\n[3/4] Triggering sync for existing blueprint '{existing_bp_id}'...")
            sync_resp = client.post(f"{RENDER_API_BASE}/blueprints/{existing_bp_id}/sync")
            if sync_resp.status_code not in (200, 201, 202):
                print(f"  ⚠️ Sync returned HTTP {sync_resp.status_code}: {sync_resp.text}")
            else:
                print("  ✅ Blueprint sync initiated successfully.")
        else:
            print(f"\n[3/4] Creating new blueprint deployment from {REPO_URL} (branch: {BRANCH})...")
            payload = {
                "name": "askforwrite-ai-company-os",
                "repo": REPO_URL,
                "branch": BRANCH,
                "ownerId": owner_id,
                "autoDeploy": "yes",
            }
            create_resp = client.post(f"{RENDER_API_BASE}/blueprints", json=payload)
            if create_resp.status_code in (200, 201):
                bp_data = create_resp.json()
                bp_obj = bp_data.get("blueprint", bp_data)
                print(f"  ✅ Blueprint created! (ID: {bp_obj.get('id')})")
            else:
                print(f"  ⚠️ Blueprint creation returned HTTP {create_resp.status_code}: {create_resp.text}")

        # 4. Fetch Web Services & Target Hostname
        print("\n[4/4] Locating web service and custom domain routing...")
        time.sleep(3)
        services_resp = client.get(f"{RENDER_API_BASE}/services?limit=20")
        target_hostname = None
        if services_resp.status_code == 200:
            services = services_resp.json()
            for s_item in services:
                srv = s_item.get("service", s_item)
                if "askforwrite" in srv.get("name", "").lower() and srv.get("type") == "web_service":
                    service_details = srv.get("serviceDetails", {})
                    target_hostname = service_details.get("url")
                    print(f"  ✅ Found Web Service: {srv.get('name')}")
                    print(f"  🌐 Service Default URL: {target_hostname}")
                    break

        print("\n" + "=" * 70)
        print(" 🎉 Deployment Process Initiated on Render.com!")
        if target_hostname:
            clean_host = target_hostname.replace("https://", "").replace("http://", "").rstrip("/")
            print("\n 👉 Hostinger DNS Record to add:")
            print("    Type:   CNAME")
            print("    Name:   os")
            print(f"    Target: {clean_host}")
            print("    TTL:    300 (or Default)")
        else:
            print("\n Monitor live build progress at: https://dashboard.render.com/blueprints")
        print("=" * 70 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy AskforWrite AI Company OS to Render.com")
    parser.add_argument("--api-key", help="Render API Key (rnd_...)")
    args = parser.parse_args()

    api_key = args.api_key or os.getenv("RENDER_API_KEY")
    if not api_key:
        print("\n[!] Please provide your Render API Key.")
        print("    You can create one in 10 seconds at: https://dashboard.render.com/account/api-keys")
        print("    Usage: python scripts/deploy_render.py --api-key rnd_xxxxxxxxxxxx\n")
        return 1

    try:
        deploy_blueprint(api_key)
        return 0
    except Exception as exc:
        print(f"\n[X] Deployment Error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
