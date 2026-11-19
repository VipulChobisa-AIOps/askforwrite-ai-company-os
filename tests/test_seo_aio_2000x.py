"""Comprehensive SEO, AIO & GEO verification tests for os.askforwrite.com."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from app.main import app
from app.services.catalog import CATALOG

client = TestClient(app)
BASE = "https://os.askforwrite.com"


def test_root_ssr_homepage_for_all_bots_and_json_for_api() -> None:
    # 1. API client (default TestClient Accept: */*, no bot UA) keeps JSON contract
    api_r = client.get("/")
    assert api_r.status_code == 200
    assert api_r.json()["status"] == "online"

    # 2. Every search & AI crawler gets 200 OK public SSR HTML5 homepage (NOT a 302 to Admin Dashboard)
    for ua in (
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "OAI-SearchBot/1.0; +https://openai.com/searchbot",
        "ChatGPT-User/1.0",
        "GPTBot/1.1",
        "PerplexityBot/1.0",
        "ClaudeBot/1.0",
        "Google-Extended",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0",
    ):
        r = client.get("/", headers={"User-Agent": ua}, follow_redirects=False)
        assert r.status_code == 200, f"UA {ua} got {r.status_code}"
        assert "text/html" in r.headers["content-type"]
        assert '<link rel="canonical" href="https://os.askforwrite.com/">' in r.text
        assert 'property="og:image" content="https://os.askforwrite.com/og-image.png"' in r.text
        assert 'name="twitter:card" content="summary_large_image"' in r.text
        assert "Admin Dashboard" not in r.text


def test_sitemap_has_all_16_skus_5_solutions_4_legal_lastmod_and_zero_duplicates() -> None:
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    root = ET.fromstring(r.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [el.find("sm:loc", ns).text for el in root.findall("sm:url", ns)]
    lastmods = [el.find("sm:lastmod", ns) for el in root.findall("sm:url", ns)]
    assert all(lm is not None and len(lm.text or "") == 10 for lm in lastmods)

    assert f"{BASE}/" in locs
    assert f"{BASE}/services" in locs
    assert f"{BASE}/solutions" in locs
    for sku in CATALOG:
        assert f"{BASE}/services/{sku}" in locs, f"Missing SKU {sku} from sitemap"
    # Zero non-canonical duplicate /services/{hyphen-slug} or raw JSON API URLs
    assert f"{BASE}/services/warehouse-automation" not in locs
    assert f"{BASE}/v1/revenue/catalog" not in locs


def test_legacy_service_hyphen_aliases_301_to_solutions() -> None:
    for slug in ("warehouse-automation", "field-force", "produce-quality-ai", "urban-mobility-ai", "seo-blog-copilot"):
        r = client.get(f"/services/{slug}", follow_redirects=False)
        assert r.status_code == 301
        assert r.headers["location"] == f"/solutions/{slug}"


def test_robots_llms_full_security_favicon_og_image_and_301_slashes() -> None:
    rob = client.get("/robots.txt")
    assert rob.status_code == 200
    for token in ("OAI-SearchBot", "ChatGPT-User", "Google-Extended", "Disallow: /v1/pay/", "Allow: /llms-full.txt"):
        assert token in rob.text

    full = client.get("/llms-full.txt")
    assert full.status_code == 200
    assert "UDYAM-RJ-14-0018404" in full.text
    assert "operations_suite" in full.text

    sec = client.get("/.well-known/security.txt")
    assert sec.status_code == 200 and "mailto:info@askforwrite.in" in sec.text

    fav = client.get("/favicon.ico")
    assert fav.status_code == 200 and len(fav.content) > 500

    og = client.get("/og-image.png")
    assert og.status_code == 200 and og.content[:4] == b"\x89PNG"

    assert client.get("/dashboard", follow_redirects=False).status_code == 301
    assert client.get("/services/", follow_redirects=False).status_code == 301
    assert client.get("/solutions/", follow_redirects=False).status_code == 301


def test_legal_pages_negotiate_html_for_browsers_and_json_for_api() -> None:
    for path in ("/legal/tos", "/legal/privacy", "/legal/declaration", "/legal/refund-policy"):
        # API default -> JSON
        r_api = client.get(path)
        assert r_api.status_code == 200
        assert "application/json" in r_api.headers["content-type"]

        # Browser / Googlebot -> HTML5 with canonical + OG + WebPage schema
        r_html = client.get(path, headers={"Accept": "text/html", "User-Agent": "Googlebot/2.1"})
        assert r_html.status_code == 200
        assert "text/html" in r_html.headers["content-type"]
        assert f'rel="canonical" href="{BASE}{path}"' in r_html.text
        assert 'og:image' in r_html.text


def test_no_fake_verification_placeholders_and_unified_org_sameas() -> None:
    for path in ("/", "/services", "/solutions", "/solutions/warehouse-automation", "/solutions/urban-mobility-ai", "/services/operations_suite"):
        r = client.get(path, headers={"Accept": "text/html", "User-Agent": "Googlebot/2.1"})
        assert r.status_code == 200
        assert "verification-ready" not in r.text
        assert "Cache-Control" in r.headers
        title_m = re.search(r"<title>(.*?)</title>", r.text, re.S)
        assert title_m and len(title_m.group(1)) <= 65, f"{path} title too long: {title_m.group(1) if title_m else ''}"
        ld_m = re.search(r'<script type="application/ld\+json">(.*?)</script>', r.text, re.S)
        assert ld_m
        graph = json.loads(ld_m.group(1))["@graph"]
        orgs = [n for n in graph if n.get("@type") == "Organization"]
        assert len(orgs) == 1
        assert orgs[0]["legalName"] == "ASKFORWRITE"
        assert "https://askforwrite.com" in orgs[0]["sameAs"]


def test_checkout_noindex_and_branded_html_404() -> None:
    ck = client.get("/v1/pay/checkout?package=growth")
    assert ck.status_code == 200
    assert "noindex, nofollow" in ck.headers.get("x-robots-tag", "").lower()
    assert 'content="noindex, nofollow"' in ck.text

    nf_browser = client.get("/this-route-does-not-exist", headers={"Accept": "text/html"})
    assert nf_browser.status_code == 404
    assert "text/html" in nf_browser.headers["content-type"]
    assert "404 — Page Not Found" in nf_browser.text

    nf_api = client.get("/v1/nonexistent-endpoint")
    assert nf_api.status_code == 404
    assert "application/json" in nf_api.headers["content-type"]
