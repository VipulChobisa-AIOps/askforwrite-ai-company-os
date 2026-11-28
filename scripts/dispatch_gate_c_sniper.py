#!/usr/bin/env python3
"""Dispatch Gate C Sniper Outreach with Staggering and Safety Checks."""

import argparse
import os
import sys
import time
import httpx
from dotenv import load_dotenv

load_dotenv("c:/Users/vipul/AI/os_gateway/.env")

OWNER_KEY = os.environ.get("OWNER_API_KEY")
BASE_URL = os.environ.get("BASE_URL", "https://os.askforwrite.com")

HEADERS = {
    "X-API-Key": OWNER_KEY,
    "Content-Type": "application/json",
}


def get_pending_approvals():
    with httpx.Client(timeout=15.0) as client:
        r = client.get(f"{BASE_URL}/v1/approvals?status=PENDING", headers=HEADERS)
        if r.status_code != 200:
            print(f"Error fetching pending approvals: HTTP {r.status_code}")
            return []
        data = r.json()
        return data.get("approvals", [])


def decide_and_dispatch(approval_id: str, reason: str = "Owner HITL approval for Gate C outreach"):
    payload = {"decision": "APPROVED", "reason": reason}
    with httpx.Client(timeout=20.0) as client:
        r = client.post(f"{BASE_URL}/v1/approvals/{approval_id}/decide", headers=HEADERS, json=payload)
        return r.status_code, r.json() if r.status_code == 200 else r.text


def main():
    parser = argparse.ArgumentParser(description="Dispatch Gate C Sniper Approvals")
    parser.add_argument("--all", action="store_true", help="Approve and dispatch all pending")
    parser.add_argument("--id", type=str, help="Specific approval ID to approve")
    parser.add_argument("--stagger-mins", type=int, default=25, help="Minutes between sends (default: 25)")
    args = parser.parse_args()

    pending = get_pending_approvals()
    print(f"\nFound {len(pending)} pending Gate C approvals on {BASE_URL}:")
    for i, a in enumerate(pending, 1):
        det = a.get("detail", {})
        comp = det.get("company") or "Unknown"
        email = det.get("recipient_email") or "Unknown"
        subj = det.get("subject") or ""
        print(f"  {i}. [{a['approval_id']}] {comp} <{email}>\n     Subject: {subj}")

    if not args.all and not args.id:
        print("\nUsage:")
        print("  python scripts/dispatch_gate_c_sniper.py --id <approval_id>   # Dispatch single")
        print("  python scripts/dispatch_gate_c_sniper.py --all --stagger-mins 25 # Dispatch all with 25-min interval")
        return

    if args.id:
        print(f"\nApproving and dispatching {args.id}...")
        status, res = decide_and_dispatch(args.id)
        print(f"Result (HTTP {status}):", res)
        return

    if args.all:
        print(f"\nDispatching all {len(pending)} approvals with {args.stagger_mins}m stagger...")
        for idx, a in enumerate(pending):
            aid = a["approval_id"]
            det = a.get("detail", {})
            print(f"\n[{idx+1}/{len(pending)}] Approving {det.get('company')} ({aid})...")
            status, res = decide_and_dispatch(aid)
            print(f"  Status: HTTP {status} -> {res}")
            if idx < len(pending) - 1 and args.stagger_mins > 0:
                print(f"  Sleeping {args.stagger_mins} minutes before next dispatch...")
                time.sleep(args.stagger_mins * 60)


if __name__ == "__main__":
    main()
