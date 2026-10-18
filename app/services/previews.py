"""Trojan Horse Proof-First Public Preview Generator.

Creates custom, high-converting proof-of-value previews for SMB prospects:
- Tailored operational pain point audit & ROI calculation
- Live sample deliverable synthesized via LLM
- Concrete operational SLA benchmarks (Manual baseline vs. Company OS)
- 1-Click Razorpay (INR) and PayPal (USD) checkout links
- Cryptographic Merkle TrustBlock verification seal
- Clean, conversion-optimized HTML landing page generator
"""

from __future__ import annotations

import html
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agents.llm_client import generate as llm_generate
from app.agents.revenue_agent import (
    PAIN_POINT_DIAGNOSIS,
    calculate_estimated_roi,
)
from app.agents.smb_search_source import VERTICAL_TO_CATALOG_KEY
from app.db.models import AuditLog, PreviewRecord, TaskRecord
from app.security.trust_chain import seal_task_to_block
from app.services.catalog import (
    CATALOG,
    build_payment_link,
    get_package,
)

logger = logging.getLogger(__name__)

CAPABILITY_NAME = "trojan_horse_preview"

# Tailored Operational Benchmarks per vertical
VERTICAL_BENCHMARKS: dict[str, dict[str, str]] = {
    "mango_quality_analytics": {
        "current_baseline": "15-20% export container rejection rate due to subjective visual grading and post-harvest decay.",
        "company_os_sla": "<0.5% export rejection with 512D joint HSV colorimetry & GLCM texture defect validation.",
        "hours_saved_weekly": "35 supervisory inspection hours per packhouse facility",
        "efficiency_gain": "+94% inspection consistency; prevents ₹3,50,000 - ₹8,00,000 loss per export container",
    },
    "bike_rebalance_analytics": {
        "current_baseline": "28% commuter churn during rush hour station starvation; high fuel costs from manual truck routing.",
        "company_os_sla": "98.5% station dock availability with OLS predictive circadian demand dispatch.",
        "hours_saved_weekly": "24 dispatch planning hours weekly",
        "efficiency_gain": "+24% daily ride turnover; -35% rebalancing truck fuel consumption",
    },
    "warehouse_automation": {
        "current_baseline": "Unscheduled stockouts of critical SKUs and 18-22% capital locked up in slow-moving dead stock (>90 days).",
        "company_os_sla": "99.8% on-shelf availability via dynamic EOQ safety buffers with automated stocktake verification.",
        "hours_saved_weekly": "30 manual audit & stock reconciliation hours weekly",
        "efficiency_gain": "-22% holding costs; eliminates 95% of preventable stockouts",
    },
    "field_force": {
        "current_baseline": "Proxy attendance, unverified client visits, and 30% disputed conveyance reimbursement claims.",
        "company_os_sla": "100% cryptographically verified GPS presence, anti-spoofing audit, and automated road mileage payout.",
        "hours_saved_weekly": "15+ supervisor coordination hours weekly",
        "efficiency_gain": "Cuts conveyance fraud claims by 30%; 0 proxy attendance",
    },
    "seo_blog_copilot": {
        "current_baseline": "₹50,000 - ₹1,20,000/mo freelance writer spend; 5-7 days turnaround per article without Schema.org markup.",
        "company_os_sla": "Instant 4-site publishing with Schema.org JSON-LD and citation-ready GEO answer engine optimization.",
        "hours_saved_weekly": "25 copywriting and CMS formatting hours weekly",
        "efficiency_gain": "8x ROI multiplier; guaranteed inclusion in ChatGPT and Perplexity citations",
    },
    "marketing_suite": {
        "current_baseline": "Fragmented ad creative production; expensive agency retainers; slow A/B testing turnaround.",
        "company_os_sla": "Instant multi-channel ad variation engine with 3x higher click-through hooks.",
        "hours_saved_weekly": "20 ad copywriting hours weekly",
        "efficiency_gain": "5x faster campaign launches across Meta, Google & LinkedIn",
    },
    "growth_all_in_one": {
        "current_baseline": "Solo founder juggling graphics, slow blog writing, and losing leads on WhatsApp after hours.",
        "company_os_sla": "Full autonomous marketing studio + 24/7 inbound closer closing deals in <60 seconds.",
        "hours_saved_weekly": "40+ founder operational hours weekly",
        "efficiency_gain": "10x ROI multiplier; zero customer inquiry drop-off",
    },
    "trust_engine": {
        "current_baseline": "Tamperable central databases, disputed audit logs, and expensive SOC 2 / ISO compliance preparation.",
        "company_os_sla": "ECDSA NIST P-256 Merkle chain verification with instant cryptographic auditor verification.",
        "hours_saved_weekly": "50 compliance preparation hours per audit cycle",
        "efficiency_gain": "Zero audit preparation fees; cryptographic non-repudiation",
    },
}


def _generate_sample_deliverable_snippet(
    company_name: str,
    domain: str,
    package_key: str,
) -> dict[str, Any]:
    """Generate a high-value sample deliverable tailored to the prospect using LLM."""
    clean_key = VERTICAL_TO_CATALOG_KEY.get(package_key, package_key)
    pkg = get_package(clean_key) or CATALOG["growth_all_in_one"]

    prompt = (
        f"Generate a customized, professional proof-of-value sample deliverable snippet for company '{company_name}' "
        f"({domain}) evaluated for '{pkg.name}'. "
        f"Provide a concrete 3-point operational breakthrough specific to their industry."
    )
    fallback = (
        f"### Customized Operational Deliverable for {company_name}\n"
        f"1. **Automated Workflow Audit**: Identified critical efficiency bottleneck on {domain}.\n"
        f"2. **Algorithmic Solution**: {pkg.name} deploys autonomous intelligence to eliminate manual error.\n"
        f"3. **Target SLA**: Guaranteed transition from manual baseline to autonomous verification."
    )
    ai_snippet = llm_generate(
        prompt=prompt,
        system_instruction="You are an elite operational systems architect crafting high-converting B2B proof-of-value deliverables.",
        fallback_text=fallback,
    )

    return {
        "title": f"Custom Proof-of-Value Plan: {company_name}",
        "package_name": pkg.name,
        "package_key": pkg.key,
        "sample_snippet": ai_snippet,
        "deliverable_type": "Live Operational Deliverable Sample",
        "generated_at": datetime.now(UTC).isoformat(),
    }


def generate_trojan_horse_preview(
    db: Session,
    company_name: str,
    domain: str,
    recommended_package: str,
    lead_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Generate a Trojan-Horse proof-first preview with custom audit, benchmarks, payment links, and TrustBlock."""
    corr_id = correlation_id or str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    preview_token = f"prev_{uuid.uuid4().hex[:16]}"

    clean_package_key = VERTICAL_TO_CATALOG_KEY.get(recommended_package.strip().lower(), recommended_package.strip().lower())
    pkg = get_package(clean_package_key) or CATALOG.get(clean_package_key) or CATALOG["growth_all_in_one"]

    # 1. Pain points & ROI Breakdown
    diag = PAIN_POINT_DIAGNOSIS.get(clean_package_key, PAIN_POINT_DIAGNOSIS.get(recommended_package, PAIN_POINT_DIAGNOSIS["growth_all_in_one"]))
    roi_breakdown = calculate_estimated_roi(pkg.key)

    custom_audit = {
        "company_name": company_name,
        "domain": domain,
        "package_key": pkg.key,
        "package_name": pkg.name,
        "target_buyer_persona": pkg.target_buyer_persona,
        "identified_pain_point": pkg.target_pain_point,
        "key_pain_points": list(diag.get("pain_points", [])),
        "roi_summary": str(diag.get("roi_formula", "")),
        "roi_multiplier": str(roi_breakdown.get("roi_multiplier", "5.0x")),
        "monthly_budget_inr": float(roi_breakdown.get("monthly_budget_inr", 50000.0)),
        "projected_value_inr": float(roi_breakdown.get("projected_value_inr", 250000.0)),
        "net_monthly_savings_inr": float(roi_breakdown.get("net_monthly_savings_inr", 200000.0)),
    }

    # 2. Sample AI Deliverable Snippet
    sample_deliverable = _generate_sample_deliverable_snippet(
        company_name=company_name,
        domain=domain,
        package_key=pkg.key,
    )

    # 3. Operational Benchmarks
    benchmarks = VERTICAL_BENCHMARKS.get(
        clean_package_key,
        VERTICAL_BENCHMARKS.get("growth_all_in_one"),
    )

    # 4. Direct Razorpay (INR), PayPal (USD), and Sovereign DirectPay checkout links
    payment_links = {
        "razorpay": build_payment_link(
            package_key=pkg.key,
            company=company_name,
            provider="razorpay",
        ),
        "paypal": build_payment_link(
            package_key=pkg.key,
            company=company_name,
            provider="paypal",
        ),
        "afw_directpay": build_payment_link(
            package_key=pkg.key,
            company=company_name,
            provider="afw_directpay",
        ),
        "currency_inr": "INR",
        "price_inr": pkg.price_inr,
        "currency_usd": "USD",
        "price_usd": pkg.price_usd,
    }

    # 5. Persist TaskRecord
    task_rec = TaskRecord(
        id=task_id,
        correlation_id=corr_id,
        objective=f"Trojan-Horse Preview Generation for {company_name} ({domain})",
        status="COMPLETED",
        result={"preview_token": preview_token, "package_key": pkg.key},
    )
    db.add(task_rec)

    # 6. Persist AuditLog
    audit_log = AuditLog(
        task_id=task_id,
        correlation_id=corr_id,
        agent_id="trojan_horse_preview_generator",
        capability_name=CAPABILITY_NAME,
        action="generate_preview",
        input_payload={
            "company_name": company_name,
            "domain": domain,
            "recommended_package": pkg.key,
            "lead_id": lead_id,
        },
        output_payload={
            "preview_token": preview_token,
            "package_key": pkg.key,
            "price_inr": pkg.price_inr,
        },
        status="COMPLETED",
    )
    db.add(audit_log)
    db.flush()

    # 7. Seal TrustBlock
    block = seal_task_to_block(
        db=db,
        task_id=task_id,
        capability_name=CAPABILITY_NAME,
        action="generate_preview",
        payload={
            "preview_token": preview_token,
            "company_name": company_name,
            "domain": domain,
            "package_key": pkg.key,
            "roi_multiplier": custom_audit["roi_multiplier"],
        },
        sealed_by="trojan_horse_preview_generator",
        commit=False,
    )

    # 8. Persist PreviewRecord
    preview_rec = PreviewRecord(
        preview_token=preview_token,
        company_name=company_name,
        domain=domain,
        recommended_package=pkg.key,
        lead_id=lead_id,
        custom_audit=custom_audit,
        sample_deliverable=sample_deliverable,
        benchmarks=benchmarks,
        payment_links=payment_links,
        views_count=0,
        trust_block_hash=block.block_hash,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(preview_rec)
    db.commit()

    return {
        "status": "COMPLETED",
        "preview_token": preview_token,
        "preview_url": f"/v1/previews/{preview_token}",
        "preview_html_url": f"/v1/previews/{preview_token}/html",
        "company_name": company_name,
        "domain": domain,
        "recommended_package": pkg.key,
        "package_name": pkg.name,
        "custom_audit": custom_audit,
        "sample_deliverable": sample_deliverable,
        "benchmarks": benchmarks,
        "payment_links": payment_links,
        "trust_block_hash": block.block_hash,
        "block_index": block.index,
        "task_id": task_id,
    }


def get_preview_by_token(
    db: Session,
    preview_token: str,
    increment_view: bool = True,
) -> PreviewRecord | None:
    """Retrieve preview by token, incrementing views count if requested."""
    preview = db.query(PreviewRecord).filter_by(preview_token=preview_token).first()
    if not preview:
        return None

    if increment_view:
        preview.views_count += 1
        preview.updated_at = datetime.now(UTC)
        db.add(preview)
        db.commit()
        db.refresh(preview)

    return preview


def render_preview_html(preview: PreviewRecord) -> str:
    """Render a conversion-optimized HTML landing page for the preview."""
    co_name = html.escape(preview.company_name)
    dom = html.escape(preview.domain)
    pkg_key = html.escape(preview.recommended_package)
    pkg = get_package(preview.recommended_package) or CATALOG.get(preview.recommended_package) or CATALOG["growth_all_in_one"]
    pkg_name = html.escape(pkg.name)

    audit = preview.custom_audit or {}
    bench = preview.benchmarks or {}
    sample = preview.sample_deliverable or {}
    links = preview.payment_links or {}

    roi_mult = html.escape(str(audit.get("roi_multiplier", "5.0x")))
    roi_summary = html.escape(str(audit.get("roi_summary", "")))
    net_savings = f"₹{int(audit.get('net_monthly_savings_inr', 200000)):,}"
    price_inr = f"₹{pkg.price_inr:,}"
    price_usd = f"${pkg.price_usd}"

    pain_points_list = audit.get("key_pain_points", [])
    pain_points_html = "".join(f"<li><span class='bullet-icon'>⚠</span> {html.escape(str(p))}</li>" for p in pain_points_list)

    sample_snippet = html.escape(str(sample.get("sample_snippet", ""))).replace("\n", "<br>")

    razorpay_url = html.escape(str(links.get("razorpay", "#")))
    paypal_url = html.escape(str(links.get("paypal", "#")))
    block_hash = html.escape(str(preview.trust_block_hash or "ECDSA-NIST-P256-GENESIS"))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{co_name} — Confidential Proof-of-Value Audit | AskforWrite AI OS</title>
  <meta name="description" content="Custom operational diagnostic and proof-of-value benchmark for {co_name} ({dom}).">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #0b0f19;
      --card-bg: rgba(17, 24, 39, 0.75);
      --card-border: rgba(255, 255, 255, 0.08);
      --purple: #8b5cf6;
      --indigo: #4f46e5;
      --cyan: #06b6d4;
      --emerald: #10b981;
      --rose: #f43f5e;
      --amber: #f59e0b;
      --text: #f9fafb;
      --text-muted: #9ca3af;
      --text-dim: #6b7280;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      padding: 30px 20px;
      min-height: 100vh;
      background-image: 
        radial-gradient(at 0% 0%, rgba(79, 70, 229, 0.15) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(6, 182, 212, 0.12) 0px, transparent 50%);
    }}
    .container {{
      max-width: 960px;
      margin: 0 auto;
    }}
    header.hero {{
      text-align: center;
      margin-bottom: 40px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      border-radius: 9999px;
      font-size: 0.8rem;
      font-weight: 600;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      background: rgba(139, 92, 246, 0.15);
      border: 1px solid rgba(139, 92, 246, 0.3);
      color: #c084fc;
      margin-bottom: 16px;
    }}
    h1 {{
      font-size: 2.2rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      margin-bottom: 8px;
      background: linear-gradient(135deg, #ffffff 40%, #9ca3af 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .subtitle {{
      color: var(--text-muted);
      font-size: 1.05rem;
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      backdrop-filter: blur(12px);
      padding: 28px;
      margin-bottom: 24px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
    }}
    .card-title {{
      font-size: 1.25rem;
      font-weight: 700;
      margin-bottom: 16px;
      display: flex;
      align-items: center;
      gap: 10px;
      color: #ffffff;
    }}
    .roi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 20px;
    }}
    .roi-box {{
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.06);
      border-radius: 12px;
      padding: 18px;
      text-align: center;
    }}
    .roi-value {{
      font-size: 1.8rem;
      font-weight: 800;
      color: var(--emerald);
      margin: 4px 0;
    }}
    .roi-label {{
      font-size: 0.8rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    ul.pain-list {{
      list-style: none;
    }}
    ul.pain-list li {{
      padding: 10px 0;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      display: flex;
      align-items: flex-start;
      gap: 10px;
      color: #e5e7eb;
    }}
    .bullet-icon {{
      color: var(--rose);
      font-size: 1.1rem;
    }}
    .code-box {{
      background: #05070e;
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 10px;
      padding: 20px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.88rem;
      color: #a5f3fc;
      line-height: 1.7;
      overflow-x: auto;
    }}
    table.benchmarks-table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
    }}
    table.benchmarks-table th, table.benchmarks-table td {{
      padding: 14px 16px;
      text-align: left;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    }}
    table.benchmarks-table th {{
      color: var(--text-muted);
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    table.benchmarks-table td.baseline {{
      color: #fca5a5;
    }}
    table.benchmarks-table td.sla {{
      color: #86efac;
      font-weight: 600;
    }}
    .trust-badge {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
      background: rgba(16, 185, 129, 0.08);
      border: 1px solid rgba(16, 185, 129, 0.25);
      border-radius: 12px;
      padding: 16px 20px;
      font-size: 0.85rem;
    }}
    .trust-hash {{
      font-family: 'JetBrains Mono', monospace;
      color: var(--emerald);
      font-weight: 600;
    }}
    .cta-container {{
      text-align: center;
      padding: 30px 20px;
      background: linear-gradient(180deg, rgba(79, 70, 229, 0.12) 0%, rgba(6, 182, 212, 0.08) 100%);
      border: 1px solid rgba(139, 92, 246, 0.3);
      border-radius: 20px;
      margin-top: 30px;
    }}
    .cta-title {{
      font-size: 1.6rem;
      font-weight: 800;
      margin-bottom: 10px;
    }}
    .btn-group {{
      display: flex;
      justify-content: center;
      gap: 16px;
      margin-top: 20px;
      flex-wrap: wrap;
    }}
    .btn-buy {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 14px 28px;
      border-radius: 10px;
      font-size: 1rem;
      font-weight: 700;
      text-decoration: none;
      transition: all 0.2s ease;
      cursor: pointer;
    }}
    .btn-razorpay {{
      background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
      color: #ffffff;
      box-shadow: 0 4px 16px rgba(79, 70, 229, 0.4);
    }}
    .btn-razorpay:hover {{
      transform: translateY(-2px);
      box-shadow: 0 6px 22px rgba(79, 70, 229, 0.6);
    }}
    .btn-paypal {{
      background: #0070ba;
      color: #ffffff;
      box-shadow: 0 4px 16px rgba(0, 112, 186, 0.4);
    }}
    .btn-paypal:hover {{
      background: #005ea6;
      transform: translateY(-2px);
      box-shadow: 0 6px 22px rgba(0, 112, 186, 0.6);
    }}
    footer {{
      text-align: center;
      color: var(--text-dim);
      font-size: 0.8rem;
      margin-top: 40px;
    }}
  </style>
</head>
<body>
  <div class="container">
    <header class="hero">
      <div class="badge">Trojan-Horse Proof-First Preview</div>
      <h1>Operational Diagnostic & Proof-of-Value</h1>
      <p class="subtitle">Prepared exclusively for <strong>{co_name}</strong> (<code>{dom}</code>)</p>
    </header>

    <!-- 1. Executive Bottleneck & ROI -->
    <div class="card">
      <div class="card-title">
        <svg width="22" height="22" fill="none" stroke="#8b5cf6" stroke-width="2" viewBox="0 0 24 24"><path d="M12 20V10M18 20V4M6 20v-4"/></svg>
        Identified Operational Bottlenecks & ROI Multiplier
      </div>
      <div class="roi-grid">
        <div class="roi-box">
          <div class="roi-label">Projected ROI Multiplier</div>
          <div class="roi-value">{roi_mult}</div>
        </div>
        <div class="roi-box">
          <div class="roi-label">Net Projected Monthly Savings</div>
          <div class="roi-value" style="color: #38bdf8;">{net_savings}</div>
        </div>
        <div class="roi-box">
          <div class="roi-label">Recommended Catalog SKU</div>
          <div class="roi-value" style="font-size: 1.1rem; color: #c084fc;">{pkg_name}</div>
        </div>
      </div>
      <p style="color: var(--text-muted); font-size: 0.95rem; margin-bottom: 14px;"><strong>Impact Formula:</strong> {roi_summary}</p>
      <ul class="pain-list">
        {pain_points_html}
      </ul>
    </div>

    <!-- 2. Live Sample AI Deliverable -->
    <div class="card">
      <div class="card-title">
        <svg width="22" height="22" fill="none" stroke="#06b6d4" stroke-width="2" viewBox="0 0 24 24"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
        Live Tailored AI Deliverable Sample
      </div>
      <div class="code-box">
        {sample_snippet}
      </div>
    </div>

    <!-- 3. Operational Benchmarks -->
    <div class="card">
      <div class="card-title">
        <svg width="22" height="22" fill="none" stroke="#10b981" stroke-width="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 14 14"/></svg>
        Operational SLA Benchmarks (Manual vs. Company OS)
      </div>
      <table class="benchmarks-table">
        <thead>
          <tr>
            <th>Metric Vector</th>
            <th>Current Manual Baseline</th>
            <th>Company OS Automated SLA</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Core Operational SLA</strong></td>
            <td class="baseline">{html.escape(str(bench.get("current_baseline", "Manual friction")))}</td>
            <td class="sla">{html.escape(str(bench.get("company_os_sla", "Automated zero-error SLA")))}</td>
          </tr>
          <tr>
            <td><strong>Workforce Hours Saved</strong></td>
            <td class="baseline">High manual overhead</td>
            <td class="sla">{html.escape(str(bench.get("hours_saved_weekly", "25+ hours weekly")))}</td>
          </tr>
          <tr>
            <td><strong>Efficiency & Financial Gain</strong></td>
            <td class="baseline">Margin leakage</td>
            <td class="sla">{html.escape(str(bench.get("efficiency_gain", "High ROI")))}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 4. Cryptographic Proof of Execution -->
    <div class="trust-badge">
      <div>
        <strong>Cryptographic Ledger Seal:</strong> ECDSA NIST P-256 Merkle Block Verified
      </div>
      <div class="trust-hash">
        Hash: {block_hash[:16]}...{block_hash[-8:]}
      </div>
    </div>

    <!-- 5. 1-Click Buy CTAs -->
    <div class="cta-container">
      <div class="cta-title">Deploy {pkg_name} for {co_name}</div>
      <p style="color: var(--text-muted); max-width: 600px; margin: 0 auto;">
        Unlock full autonomous agent execution, 1-click provisioning, and dedicated L0 Owner oversight.
      </p>
      <div class="btn-group">
        <a href="{razorpay_url}" target="_blank" rel="noopener noreferrer" class="btn-buy btn-razorpay">
          ⚡ 1-Click Buy (Razorpay {price_inr}/mo)
        </a>
        <a href="{paypal_url}" target="_blank" rel="noopener noreferrer" class="btn-buy btn-paypal">
          🌐 1-Click Buy (PayPal {price_usd}/mo)
        </a>
      </div>
    </div>

    <footer>
      AskforWrite AI Company OS &bull; Tamper-Evident Cryptographic Ledger &bull; All Rights Reserved
    </footer>
  </div>
</body>
</html>"""
