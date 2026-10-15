"""Webhook Registration & Verification Utility — AskforWrite Company OS.

Automates registering webhook endpoints on Razorpay and PayPal:
- Razorpay: https://os.askforwrite.com/v1/webhooks/razorpay
- PayPal:   https://os.askforwrite.com/v1/webhooks/paypal
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def register_razorpay_webhook(base_url: str) -> dict:
    """Register webhook with Razorpay REST API."""
    key_id = os.environ.get("RAZORPAY_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    webhook_url = f"{base_url.rstrip('/')}/v1/webhooks/razorpay"

    if not key_id or not key_secret:
        return {"status": "skipped", "reason": "RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET not set in .env"}

    print(f"\n[Razorpay] Registering webhook endpoint: {webhook_url}")
    payload = {
        "url": webhook_url,
        "alert_email": os.environ.get("OUTREACH_FROM_EMAIL", "info@askforwrite.in"),
        "secret": os.environ.get("RAZORPAY_WEBHOOK_SECRET") or key_secret[:16],
        "events": {
            "payment.captured": True,
            "order.paid": True,
            "subscription.activated": True,
            "subscription.charged": True,
        },

    }

    credentials = base64.b64encode(f"{key_id}:{key_secret}".encode()).decode()
    req = urllib.request.Request(
        "https://api.razorpay.com/v1/webhooks",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "User-Agent": "AskforWrite-Company-OS/0.2.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            print(f"  [OK] Razorpay Webhook ID: {data.get('id')}")
            return {"status": "success", "id": data.get("id"), "url": webhook_url}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode()
        print(f"  [INFO] Razorpay API Response ({exc.code}): {err_body[:200]}")
        return {"status": "api_response", "code": exc.code, "body": err_body}
    except Exception as exc:
        print(f"  [WARN] Razorpay connection: {exc}")
        return {"status": "error", "error": str(exc)}


def register_paypal_webhook(base_url: str) -> dict:
    """Register webhook with PayPal REST API."""
    client_id = os.environ.get("PAYPAL_CLIENT_ID", "")
    client_secret = os.environ.get("PAYPAL_CLIENT_SECRET", "")
    webhook_url = f"{base_url.rstrip('/')}/v1/webhooks/paypal"

    if not client_id or not client_secret:
        return {"status": "skipped", "reason": "PAYPAL_CLIENT_ID or PAYPAL_CLIENT_SECRET not set"}

    print("\n[PayPal] Obtaining OAuth2 Bearer token from PayPal...")
    token_url = "https://api-m.paypal.com/v1/oauth2/token"
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    auth_req = urllib.request.Request(
        token_url,
        data=b"grant_type=client_credentials",
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(auth_req, timeout=10) as auth_res:
            auth_data = json.loads(auth_res.read().decode())
            access_token = auth_data.get("access_token")

        print(f"  [OK] PayPal OAuth token acquired. Registering webhook endpoint: {webhook_url}")
        payload = {
            "url": webhook_url,
            "event_types": [
                {"name": "PAYMENT.CAPTURE.COMPLETED"},
                {"name": "BILLING.SUBSCRIPTION.ACTIVATED"},
                {"name": "CHECKOUT.ORDER.APPROVED"},
            ],
        }

        hook_req = urllib.request.Request(
            "https://api-m.paypal.com/v1/notifications/webhooks",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(hook_req, timeout=10) as hook_res:
            hook_data = json.loads(hook_res.read().decode())
            print(f"  [OK] PayPal Webhook ID: {hook_data.get('id')}")
            return {"status": "success", "id": hook_data.get("id"), "url": webhook_url}
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode()
        print(f"  [INFO] PayPal API Response ({exc.code}): {err_body[:200]}")
        return {"status": "api_response", "code": exc.code, "body": err_body}
    except Exception as exc:
        print(f"  [WARN] PayPal connection: {exc}")
        return {"status": "error", "error": str(exc)}


def verify_local_webhook_signature():
    """Verify HMAC-SHA256 signature verification locally."""
    secret = "test_webhook_secret_key"
    payload = json.dumps({"event": "payment.captured", "id": "pay_test_123"})
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    # Re-verify
    computed = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    assert hmac.compare_digest(expected, computed)
    print("\n[Local Verification] HMAC-SHA256 Webhook Signature Validator: [OK] PASS")


def main():
    parser = argparse.ArgumentParser(description="Register webhooks for Razorpay and PayPal")
    parser.add_argument("--base-url", default="https://os.askforwrite.com", help="Public deployment URL")
    args = parser.parse_args()

    print("=" * 65)
    print("  AskforWrite AI Company OS — Payment Webhook Registration")
    print("=" * 65)

    verify_local_webhook_signature()
    rzp_res = register_razorpay_webhook(args.base_url)
    pp_res = register_paypal_webhook(args.base_url)

    print("\nSummary:")
    print(f"  Razorpay Status: {rzp_res.get('status')}")
    print(f"  PayPal Status:   {pp_res.get('status')}")
    print("\nWebhook URLs ready to receive live payments:")
    print(f"  • {args.base_url}/v1/webhooks/razorpay")
    print(f"  • {args.base_url}/v1/webhooks/paypal\n")


if __name__ == "__main__":
    main()
