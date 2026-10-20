#!/usr/bin/env python3
"""Poll Render service until build is deployed and healthy."""

import sys
import time
import httpx

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

URL = "https://askforwrite-ai-company-os.onrender.com/health"
print(f"Polling {URL} for live status...")

start = time.time()
while time.time() - start < 300: # 5 minutes max
    try:
        r = httpx.get(URL, timeout=8.0)
        routing = r.headers.get("x-render-routing", "")
        if r.status_code == 200:
            print(f"\n🎉 SUCCESS! Render service is LIVE (HTTP 200)!\nResponse: {r.text}\n")
            sys.exit(0)
        elif routing == "no-server":
            print(".", end="", flush=True)
        else:
            print(f"[{r.status_code}]", end="", flush=True)
    except Exception as exc:
        print("x", end="", flush=True)
    time.sleep(10)

print("\nTimed out waiting for Render build.")
sys.exit(1)
