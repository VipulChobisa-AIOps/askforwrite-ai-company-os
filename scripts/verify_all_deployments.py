import httpx
import socket
import sys
import warnings
warnings.filterwarnings('ignore')

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}

domains = [
    ("askforwrite.in", "Main Static Academic Platform (138 pages)"),
    ("os.askforwrite.in", "Company OS Subdomain (CNAME -> Render)"),
    ("os.askforwrite.com", "Company OS Control Plane (Render Production)"),
    ("ask4write.com", "Brand & Commerce WordPress Hub"),
    ("askforwrite.com", "Global Hub WordPress Site"),
    ("askforwrite.info", "Knowledge & Docs WordPress Site"),
    ("shop.ask4write.com", "Digital Paper Storefront")
]

print("\n" + "=" * 76)
print("  AskforWrite Ecosystem — Production Deployment & Widget Verification")
print("=" * 76)

all_passed = True

with httpx.Client(headers=headers, follow_redirects=True, verify=False, timeout=12.0) as client:
    for domain, label in domains:
        print(f"\nScanning: {domain} ({label})")
        
        # 1. DNS check
        try:
            ip = socket.gethostbyname(domain)
            print(f"  • DNS Resolution:   [OK] Resolves to {ip}")
        except socket.gaierror as e:
            print(f"  • DNS Resolution:   [FAIL] Could not resolve host ({e})")
            if domain == "os.askforwrite.in":
                print("    (Note: CNAME may take a few minutes to propagate across DNS resolvers)")
            all_passed = False
            continue

        # 2. HTTP Status & Content
        try:
            resp = client.get(f"https://{domain}")
            print(f"  • HTTP Status:      [HTTP {resp.status_code}]")
            
            # 3. Widget check
            html = resp.text
            has_widget = "widget.js" in html
            if has_widget:
                print("  • Sales Closer:     [OK] EMBEDDED & ACTIVE")
                # find snippet
                idx = html.find("widget.js")
                snippet = html[max(0, idx-40):min(len(html), idx+80)].replace("\n", " ").strip()
                print(f"    Snippet: ...{snippet}...")
            else:
                print("  • Sales Closer:     [NOT FOUND] 'widget.js' not present in homepage HTML")
                all_passed = False
                
        except Exception as exc:
            print(f"  • Connection Error: {type(exc).__name__} - {exc}")
            all_passed = False

print("\n" + "=" * 76)
print("  Verification Scan Complete")
print("=" * 76 + "\n")
