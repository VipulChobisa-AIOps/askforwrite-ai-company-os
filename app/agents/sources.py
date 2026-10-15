"""Source providers used for lead discovery and enrichment."""

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol

import httpx


@dataclass(frozen=True)
class SignalBundle:
    company: str
    website: str
    industry: str
    geography: str
    signals: tuple[str, ...]
    public_contact_channel: str | None = None
    do_not_contact: bool = False


class SourceProvider(Protocol):
    data_mode: str

    def search(self, query: str, limit: int = 10) -> list[SignalBundle]:
        """Return source-backed candidates for an objective."""


class OfflineSignalProvider:
    """Synthetic golden fixtures; this provider never accesses the web."""

    data_mode = "offline_synthetic"

    _fixtures = (
        SignalBundle(
            company="Rajasthan AgriLogistics Pvt Ltd",
            website="https://agrilogistics.example.com",
            industry="Agriculture Logistics",
            geography="Rajasthan, India",
            signals=(
                "hiring field supervisors across 12 districts",
                "reviews mention manual attendance problems",
                "announced fleet expansion for farm-gate collection",
            ),
            public_contact_channel="info@agrilogistics.example.com",
        ),
        SignalBundle(
            company="Jaipur Retail Chain",
            website="https://jaipurretail.example.com",
            industry="Retail Distribution",
            geography="Jaipur, India",
            signals=(
                "job posting for field sales force manager",
                "press note on opening 30 new stores",
            ),
            public_contact_channel="contact@jaipurretail.example.com",
        ),
        SignalBundle(
            company="Gujarat Warehousing Co",
            website="https://gjwarehousing.example.com",
            industry="Warehousing",
            geography="Gujarat, India",
            signals=(
                "tender for inventory control modernization",
                "report on stock discrepancy losses",
            ),
            public_contact_channel="ops@gjwarehousing.example.com",
        ),
        SignalBundle(
            company="Blocked ExampleCorp",
            website="https://blocked-example.com",
            industry="Unknown",
            geography="Unknown",
            signals=("previously requested no contact",),
            do_not_contact=True,
        ),
    )

    def search(self, query: str, limit: int = 10) -> list[SignalBundle]:
        del query
        return list(self._fixtures[:limit])


class _PageMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_text: list[str] = []
        self._in_title = False
        self._in_script = False
        self._script_type = ""
        self.meta_description = ""
        self.meta_keywords = ""
        self.og_title = ""
        self.og_description = ""
        self.has_json_ld = False
        self.headings: list[str] = []
        self._current_tag: str | None = None
        self.emails: set[str] = set()
        self.social_links: dict[str, str] = {}
        self.cms_platform: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._current_tag = tag.lower()
        attr_dict = {k.lower(): (v or "") for k, v in attrs if k}

        if self._current_tag == "title":
            self._in_title = True
        elif self._current_tag == "script":
            self._in_script = True
            self._script_type = attr_dict.get("type", "").lower()
            if "application/ld+json" in self._script_type:
                self.has_json_ld = True
        elif self._current_tag == "meta":
            name = (attr_dict.get("name") or attr_dict.get("property") or "").lower()
            content = attr_dict.get("content") or ""
            if name in ("description",) and not self.meta_description:
                self.meta_description = content.strip()
            elif name in ("og:description",) and not self.og_description:
                self.og_description = content.strip()
            elif name in ("og:title",) and not self.og_title:
                self.og_title = content.strip()
            elif name in ("keywords",) and not self.meta_keywords:
                self.meta_keywords = content.strip()
            elif "generator" in name:
                gen_val = content.lower()
                if "wordpress" in gen_val:
                    self.cms_platform = "WordPress"
                elif "shopify" in gen_val:
                    self.cms_platform = "Shopify"
        elif self._current_tag == "a":
            href = attr_dict.get("href") or ""
            if href.lower().startswith("mailto:"):
                raw_email = href[7:].split("?")[0].strip()
                if "@" in raw_email:
                    self.emails.add(raw_email.lower())
            elif "linkedin.com/company" in href.lower():
                self.social_links["linkedin"] = href
            elif "twitter.com/" in href.lower() or "x.com/" in href.lower():
                self.social_links["twitter"] = href
            elif "github.com/" in href.lower():
                self.social_links["github"] = href

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
        elif tag.lower() == "script":
            self._in_script = False
            self._script_type = ""
        self._current_tag = None

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_text.append(text)
        elif self._current_tag in ("h1", "h2", "h3"):
            if len(self.headings) < 8 and len(text) > 3:
                self.headings.append(text)

        # Body text email scanner
        found = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', text)
        for email in found:
            clean = email.lower().rstrip(".,")
            if not any(clean.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif")):
                self.emails.add(clean)


def extract_page_metadata(html: str) -> dict[str, object]:
    """Parse HTML string and extract metadata, headings, CMS tags, and SEO/GEO/AIO audit signals."""
    parser = _PageMetadataParser()
    try:
        parser.feed(html)
    except Exception:
        pass

    # Detect WordPress / Shopify fingerprints if generator tag was absent
    html_lower = html.lower()
    cms = parser.cms_platform
    if not cms:
        if "wp-content" in html_lower or "wp-includes" in html_lower:
            cms = "WordPress"
        elif "cdn.shopify.com" in html_lower:
            cms = "Shopify"

    title = " ".join(parser.title_text).strip() or parser.og_title
    meta_desc = parser.meta_description or parser.og_description

    # Synthesize SEO, GEO (Generative Engine Optimization), and AIO (AI Optimization) signals
    seo_geo_signals: list[str] = []
    if cms == "WordPress":
        seo_geo_signals.append("WordPress CMS detected — prime candidate for 4-Site SEO Blog Copilot pipeline")
    if not meta_desc:
        seo_geo_signals.append("Missing meta description — SEO gap impacting organic search click-through rate")
    else:
        seo_geo_signals.append(f"Meta description present: {meta_desc[:90]}...")

    if not parser.has_json_ld:
        seo_geo_signals.append("Missing Schema.org JSON-LD — AIO/GEO gap: low citation likelihood in ChatGPT/Perplexity")
    else:
        seo_geo_signals.append("Structured data detected — ready for AI answer engine knowledge graph injection")

    if not parser.headings:
        seo_geo_signals.append("Unstructured heading hierarchy — opportunity for semantic topical authority reorganization")

    return {
        "title": title,
        "description": meta_desc,
        "keywords": parser.meta_keywords,
        "headings": parser.headings,
        "emails": sorted(parser.emails),
        "social_links": parser.social_links,
        "cms_platform": cms,
        "has_json_ld": parser.has_json_ld,
        "seo_geo_signals": seo_geo_signals,
    }


def fetch_and_enrich_website(
    url: str,
    timeout: float = 6.0,
    client: httpx.Client | None = None,
) -> dict[str, object]:
    """Fetch website HTML and parse title, signals, and contact channel."""
    normalized_url = url.strip()
    if not normalized_url.startswith(("http://", "https://")):
        normalized_url = f"https://{normalized_url}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AskforWrite-ResearchEngine/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    
    try:
        if client:
            resp = client.get(normalized_url, headers=headers, timeout=timeout, follow_redirects=True)
        else:
            with httpx.Client(timeout=timeout, follow_redirects=True) as local_client:
                resp = local_client.get(normalized_url, headers=headers)
        
        if resp.status_code < 400:
            parsed = extract_page_metadata(resp.text)
            parsed["status_code"] = resp.status_code
            parsed["final_url"] = str(resp.url)
            return parsed
        else:
            return {
                "status_code": resp.status_code,
                "title": "",
                "description": "",
                "headings": [],
                "emails": [],
                "social_links": {},
            }
    except Exception as exc:
        return {
            "error": str(exc),
            "status_code": 0,
            "title": "",
            "description": "",
            "headings": [],
            "emails": [],
            "social_links": {},
        }


class LiveEnrichmentLeadSource:
    """Real live web scraping and signal enrichment provider for lead discovery."""

    data_mode = "live_enrichment"

    # Known live candidate directory for automated discovery when given high-level queries
    _directory = (
        {
            "company": "Shadowfax Technologies",
            "website": "https://www.shadowfax.in",
            "industry": "On-Demand Field Force Logistics & Hyperlocal Delivery",
            "geography": "Bengaluru, Karnataka, India",
            "tags": ("field", "attendance", "tracking", "gps", "sales force", "supervisor", "logistics"),
        },
        {
            "company": "FarEye Logistics",
            "website": "https://fareye.com",
            "industry": "Last Mile Logistics & Delivery",
            "geography": "Noida, Uttar Pradesh, India",
            "tags": ("logistics", "delivery", "fleet", "tracking", "dispatch"),
        },
        {
            "company": "Locus Robotics & Logistics",
            "website": "https://locus.sh",
            "industry": "Dispatch & Fleet Management",
            "geography": "Bengaluru, Karnataka, India",
            "tags": ("fleet", "dispatch", "routing", "supervisor", "geofence"),
        },
        {
            "company": "GreyOrange Robotics",
            "website": "https://www.greyorange.com",
            "industry": "Warehouse Automation & Robotics",
            "geography": "Roswell, GA, USA & India",
            "tags": ("warehouse", "inventory", "stock", "automation"),
        },
        {
            "company": "HubSpot Inbound Marketing",
            "website": "https://www.hubspot.com",
            "industry": "Marketing & CRM Software",
            "geography": "Cambridge, MA, USA",
            "tags": ("marketing", "campaign", "seo", "content", "crm"),
        },
    )

    def __init__(self, timeout: float = 6.0, client: httpx.Client | None = None) -> None:
        self.timeout = timeout
        self.client = client

    def enrich_url(self, url: str) -> dict[str, object]:
        return fetch_and_enrich_website(url, timeout=self.timeout, client=self.client)

    def search(self, query: str, limit: int = 10) -> list[SignalBundle]:
        """Search and live-enrich matching organizations from web signals."""
        normalized = query.strip().lower()
        candidates: list[SignalBundle] = []
        
        # Check if the query itself is a specific domain or comma-separated URLs
        if "." in normalized and ("/" in normalized or " " not in normalized):
            domains = [d.strip() for d in query.replace(",", " ").split() if "." in d]
            for domain in domains[:limit]:
                meta = self.enrich_url(domain)
                emails = meta.get("emails", [])
                public_channel = emails[0] if emails else None
                title = str(meta.get("title") or domain)
                description = str(meta.get("description") or "")
                headings = meta.get("headings", [])
                
                signals = []
                if title:
                    signals.append(f"page title: {title}")
                if description:
                    signals.append(f"meta description: {description}")
                for h in headings[:3]:
                    signals.append(f"heading: {h}")
                for seo_sig in meta.get("seo_geo_signals", []):
                    signals.append(f"seo_audit: {seo_sig}")
                if not signals:
                    signals.append("verified live web domain presence")
                
                # Derive clean company name
                clean_name = title.split(" - ")[0].split(" | ")[0].strip() or domain
                website = str(meta.get("final_url") or (f"https://{domain}" if not domain.startswith("http") else domain))
                
                candidates.append(
                    SignalBundle(
                        company=clean_name,
                        website=website,
                        industry="Technology & Services",
                        geography="Global",
                        signals=tuple(signals),
                        public_contact_channel=public_channel,
                    )
                )
            if candidates:
                return candidates

        # Otherwise filter directory by matching keyword tags
        matched_entries = []
        for entry in self._directory:
            score = sum(1 for tag in entry["tags"] if tag in normalized)
            matched_entries.append((score, entry))
        
        # Sort by relevance
        matched_entries.sort(key=lambda x: x[0], reverse=True)
        selected = [item[1] for item in matched_entries[:limit]]
        
        # Enrich each selected candidate live
        for entry in selected:
            meta = self.enrich_url(entry["website"])
            emails = meta.get("emails", [])
            public_channel = emails[0] if emails else None
            description = str(meta.get("description") or "")
            headings = meta.get("headings", [])
            
            signals = list(entry["tags"])
            if description:
                signals.append(f"overview: {description[:160]}")
            for h in headings[:2]:
                signals.append(f"section: {h}")
            for seo_sig in meta.get("seo_geo_signals", []):
                signals.append(f"seo_audit: {seo_sig}")
            
            candidates.append(
                SignalBundle(
                    company=entry["company"],
                    website=entry["website"],
                    industry=entry["industry"],
                    geography=entry["geography"],
                    signals=tuple(signals),
                    public_contact_channel=public_channel,
                )
            )
            
        return candidates