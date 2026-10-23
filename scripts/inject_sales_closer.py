#!/usr/bin/env python3
"""Injects the 24/7 AI Sales Closer widget into all local site HTML pages."""

import os

target_dirs = [
    r"c:\Users\vipul\AI\Documents\ask4\ASK4",
    r"c:\Users\vipul\AI\Documents\ask4\public_html",
    r"c:\Users\vipul\AI\Documents\ask4\askforwrite",
    r"c:\Users\vipul\AI\Documents\ask4\askforwrite_production_v2",
]

snippet = """
<!-- ══════ AskforWrite AI Company OS — 24/7 AI Sales Closer ══════ -->
<script src="https://os.askforwrite.com/static/widget.js" data-afw-tenant="askforwrite" async></script>
<!-- ══════════════════════════════════════════════════════════════════ -->
"""

modified = []

for td in target_dirs:
    if not os.path.exists(td):
        continue
    for root, _, files in os.walk(td):
        for f in files:
            if f.endswith(".html"):
                fpath = os.path.join(root, f)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as fp:
                        content = fp.read()
                    if "widget.js" not in content and "</body>" in content:
                        new_content = content.replace("</body>", snippet.strip() + "\n</body>")
                        with open(fpath, "w", encoding="utf-8") as fp:
                            fp.write(new_content)
                        modified.append(fpath)
                except Exception as exc:
                    print(f"Error on {fpath}: {exc}")

print(f"Successfully injected 24/7 AI Sales Closer widget into {len(modified)} HTML files across local site trees.")
for m in modified[:15]:
    print(f"  • {m}")
if len(modified) > 15:
    print(f"  ... and {len(modified) - 15} more files.")
