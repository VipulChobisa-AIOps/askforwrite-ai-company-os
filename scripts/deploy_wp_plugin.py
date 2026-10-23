import httpx
import re
import os
import warnings
warnings.filterwarnings('ignore')

import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv()

user = os.environ.get("WP_ADMIN_USER", os.environ.get("WP_USERNAME", "vipulchobisa@gmail.com"))
pwd = os.environ.get("WP_ADMIN_PASSWORD", os.environ.get("WP_APP_PASSWORD", ""))
zip_path = os.path.abspath("hostinger_deploy/askforwrite-ai-os-bridge.zip")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}

def deploy_to_site(site_url: str):
    print(f"\n{'=' * 60}")
    print(f"Deploying AskforWrite AI OS Bridge to: {site_url}")
    print(f"{'=' * 60}")
    
    client = httpx.Client(headers=headers, follow_redirects=True, verify=False, timeout=30.0)
    
    # 1. Login
    print("  [1/4] Authenticating with WordPress...")
    r_login = client.post(f"{site_url}/wp-login.php", data={
        "log": user,
        "pwd": pwd,
        "wp-submit": "Log In",
        "redirect_to": f"{site_url}/wp-admin/",
        "testcookie": "1"
    })
    if not any("wordpress_logged_in" in c for c in client.cookies.keys()):
        print("  [ERROR] Login failed!")
        return False
    print("  [OK] Successfully authenticated into wp-admin")
    
    # 2. Get Upload Nonce
    print("  [2/4] Fetching upload security nonce...")
    r_upload_page = client.get(f"{site_url}/wp-admin/plugin-install.php?tab=upload")
    nonce_match = re.search(r'name="_wpnonce"\s+value="([a-f0-9]+)"', r_upload_page.text)
    if not nonce_match:
        print("  [ERROR] Could not extract _wpnonce from plugin-install page!")
        return False
    nonce = nonce_match.group(1)
    print(f"  [OK] Extracted nonce: {nonce}")
    
    # 3. Upload Plugin ZIP
    print(f"  [3/4] Uploading {os.path.basename(zip_path)}...")
    with open(zip_path, "rb") as f:
        files = {
            "pluginzip": ("askforwrite-ai-os-bridge.zip", f, "application/zip")
        }
        data = {
            "_wpnonce": nonce,
            "_wp_http_referer": "/wp-admin/plugin-install.php?tab=upload"
        }
        r_upload = client.post(
            f"{site_url}/wp-admin/update.php?action=upload-plugin",
            data=data,
            files=files
        )
    print(f"  Upload response status: {r_upload.status_code}")
    
    # Check if plugin was installed or already exists
    activate_match = re.search(r'href="([^"]*plugins\.php\?action=activate[^"]*)"', r_upload.text)
    if not activate_match:
        # Check if already installed
        if "destination folder already exists" in r_upload.text.lower() or "already installed" in r_upload.text.lower():
            print("  [INFO] Plugin folder already exists on server, looking for activate link in plugins list...")
            r_plugins = client.get(f"{site_url}/wp-admin/plugins.php")
            activate_match = re.search(r'href="([^"]*plugins\.php\?action=activate&amp;plugin=askforwrite-ai-os-bridge[^"]*)"', r_plugins.text)
            if not activate_match:
                activate_match = re.search(r'href="([^"]*plugins\.php\?action=activate[^"]*askforwrite-ai-os-bridge[^"]*)"', r_plugins.text)
        else:
            print("  [WARN] No direct activate link found. Snippet of upload result:")
            clean_text = re.sub('<[^<]+?>', ' ', r_upload.text)[:300]
            print(f"    {clean_text.strip()}")
            # Still check plugins list
            r_plugins = client.get(f"{site_url}/wp-admin/plugins.php")
            activate_match = re.search(r'href="([^"]*plugins\.php\?action=activate[^"]*askforwrite-ai-os-bridge[^"]*)"', r_plugins.text)
    
    # 4. Activate Plugin
    if activate_match:
        activate_url = activate_match.group(1).replace("&amp;", "&")
        if not activate_url.startswith("http"):
            activate_url = f"{site_url}/wp-admin/" + activate_url.lstrip("/")
        print(f"  [4/4] Activating plugin via: {activate_url[:80]}...")
        r_act = client.get(activate_url)
        print(f"  Activation status: {r_act.status_code}")
    else:
        # Check if already active
        r_plugins = client.get(f"{site_url}/wp-admin/plugins.php")
        if "askforwrite-ai-os-bridge.php" in r_plugins.text and "action=deactivate" in r_plugins.text:
            print("  [4/4] Plugin is already ACTIVE!")
        else:
            print("  [ERROR] Could not activate plugin!")
            return False
            
    # Verification
    print("\n  ── Verifying Deployment on Live Site ──")
    r_home = client.get(site_url)
    widget_ok = "widget.js" in r_home.text
    r_llms = client.get(f"{site_url}/llms.txt")
    llms_ok = r_llms.status_code == 200 and "llms.txt" in r_llms.text.lower()
    
    print(f"  • Sales Closer Widget Embedded: {'✅ YES' if widget_ok else '❌ NO'}")
    print(f"  • 2026 /llms.txt GEO Manifest:  {'✅ SERVED (HTTP 200)' if llms_ok else '❌ INACTIVE'}")
    return widget_ok and llms_ok

if __name__ == "__main__":
    sites = [
        "https://ask4write.com",
        "https://askforwrite.com",
        "https://askforwrite.info"
    ]
    results = {}
    for s in sites:
        results[s] = deploy_to_site(s)
    
    print(f"\n{'=' * 60}")
    print("DEPLOYMENT SUMMARY:")
    for s, ok in results.items():
        print(f"  {s}: {'[OK] SUCCESS' if ok else '[!] REQUIRES ATTENTION'}")
    print(f"{'=' * 60}\n")
