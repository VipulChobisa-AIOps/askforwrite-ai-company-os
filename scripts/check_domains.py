import httpx
import warnings
warnings.filterwarnings('ignore')

domains = [
    'askforwrite.in',
    'ask4write.com',
    'shop.ask4write.com',
    'askforwrite.info',
    'askforwrite.com',
    'os.askforwrite.com',
    'os.askforwrite.in'
]

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}

print("Checking domain statuses...")
for d in domains:
    status_str = ""
    try:
        r = httpx.get(f"https://{d}", headers=headers, timeout=12.0, follow_redirects=True, verify=False)
        server = r.headers.get("server", "unknown")
        powered_by = r.headers.get("x-powered-by", "")
        title = ""
        if "<title>" in r.text.lower():
            title = r.text.split("<title>")[1].split("</title>")[0].strip() if "<title>" in r.text else ""
        status_str += f"Root: {r.status_code} ({server}, {powered_by}) - Title: '{title[:40]}'"
    except Exception as e:
        status_str += f"Root: FAILED ({type(e).__name__})"

    try:
        wp = httpx.get(f"https://{d}/wp-json/", headers=headers, timeout=6.0, follow_redirects=True, verify=False)
        status_str += f" | wp-json: {wp.status_code}"
    except Exception as e:
        status_str += f" | wp-json: FAILED"

    print(f"[{d}] -> {status_str}")
