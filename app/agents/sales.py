"""Requirement extraction and proposal drafting from recorded notes."""

from dataclasses import dataclass

NEED_KEYWORDS = {
    "field_force_management": (
        "field", "gps", "tracking", "attendance", "geofence", "workforce",
    ),
    "warehouse_automation": ("warehouse", "inventory", "stock", "storage", "stocksense"),
    "marketing_suite": ("marketing", "content", "seo", "campaign"),
    "mango_quality_analytics": ("mango", "produce", "fruit", "harvest", "ripeness", "packhouse", "agritech", "cold-chain"),
    "bike_rebalance_analytics": ("bike", "fleet", "micro-mobility", "rebalance", "dock", "station churn", "transit"),
}

CAPABILITY_DESCRIPTIONS = {
    "field_force_management": (
        "Field-force attendance, task coordination, and workforce visibility."
    ),
    "warehouse_automation": "Inventory control and warehouse layout optimization.",
    "marketing_suite": "Marketing content and campaign generation capabilities.",
    "mango_quality_analytics": "Produce computer vision grading, multi-model ripeness analysis, and shelf-life certification.",
    "bike_rebalance_analytics": "Circadian mobility demand forecasting, station churn rebalancing, and priority truck routing.",
}

BUDGET_TERMS = ("budget", "inr", "usd", "rs.", "$", "investment", "spend")
TIMELINE_TERMS = (
    "next month", "this month", "this quarter", "next quarter", "weeks",
    "within", "by end", "asap", "immediately",
)


@dataclass(frozen=True)
class SalesDraft:
    stated_needs: list[str]
    has_budget_signal: bool
    has_timeline: bool
    constraints: list[str]
    product_match: str | None
    priority: str
    proposal_title: str
    proposal_summary: str
    proposal_scope: list[dict[str, str]]


def build_sales_draft(
    company: str,
    geography: str,
    notes: str,
    lead_product_match: str | None,
) -> SalesDraft:
    normalized_notes = notes.casefold()
    stated_needs = [
        product
        for product, keywords in NEED_KEYWORDS.items()
        if any(keyword in normalized_notes for keyword in keywords)
    ]
    has_budget_signal = any(term in normalized_notes for term in BUDGET_TERMS)
    has_timeline = any(term in normalized_notes for term in TIMELINE_TERMS)
    constraints = (
        ["multi-location rollout"]
        if "district" in normalized_notes or "location" in normalized_notes
        else []
    )
    qualification_score = (
        int(bool(stated_needs)) + int(has_budget_signal) + int(has_timeline)
    )
    priority = "HIGH" if qualification_score == 3 else "MEDIUM" if qualification_score == 2 else "LOW"
    product_match = (
        lead_product_match
        if lead_product_match in stated_needs
        else stated_needs[0]
        if stated_needs
        else None
    )
    proposal_scope = [
        {
            "capability": product,
            "description": CAPABILITY_DESCRIPTIONS[product],
            "delivery": "subject to owner-approved capability selection",
        }
        for product in stated_needs
    ]
    proposal_title = f"Proposal: {company} - {product_match or 'requirement review'}"
    proposal_summary = (
        f"Prepared for {company} ({geography}). Captured needs: "
        f"{', '.join(stated_needs) if stated_needs else 'needs clarification'}. "
        f"Priority: {priority}. Pricing and final scope require owner review."
    )
    return SalesDraft(
        stated_needs=stated_needs,
        has_budget_signal=has_budget_signal,
        has_timeline=has_timeline,
        constraints=constraints,
        product_match=product_match,
        priority=priority,
        proposal_title=proposal_title,
        proposal_summary=proposal_summary,
        proposal_scope=proposal_scope,
    )