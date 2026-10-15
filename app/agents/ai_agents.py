"""
AI-powered agent implementations with LangSmith tracing.
======================================================
Wraps existing deterministic logic or provides AI-native implementations
for Discovery, Research, Sales, and Manager agents.
"""

import json

from langsmith import traceable

from app.agents.discovery import _score
from app.agents.llm_client import generate

# --- Discovery AI Agent ---

@traceable(name="ai_discovery_agent", run_type="chain")
def ai_score_lead(company: str, signals: tuple[str, ...]) -> dict[str, object]:
    """Uses LLM to evaluate lead fit instead of deterministic keyword counting."""
    prompt = f"""
    Evaluate the following company based on observed signals.
    Company: {company}
    Signals: {'; '.join(signals)}
    
    Determine if this company is a good fit for one of our products:
    - field_force_management
    - warehouse_automation
    - marketing_suite
    
    Return a JSON object with:
    - product_match: (string or null) The best matching product.
    - fit_score: (float 0.0 to 1.0) Confidence in the match.
    - reasoning: (string) Why this product is a fit.
    """
    
    response_text = generate(
        prompt=prompt,
        system_instruction="You are a B2B lead qualification expert. Always output valid JSON.",
        temperature=0.2
    )
    
    try:
        # Strip code fences if present
        clean_json = response_text.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean_json)
        return {
            "product_match": result.get("product_match"),
            "fit_score": float(result.get("fit_score", 0.0)),
            "reasoning": result.get("reasoning", "")
        }
    except Exception:
        # Fallback to deterministic scoring if parsing fails
        fit_score, product_match = _score(signals)
        return {
            "product_match": product_match,
            "fit_score": fit_score,
            "reasoning": "Fallback to deterministic scoring due to LLM parsing error."
        }


# --- Sales AI Agent ---

@traceable(name="ai_sales_agent", run_type="chain")
def ai_draft_proposal(company: str, geography: str, notes: str, lead_product_match: str | None) -> dict[str, object]:
    """Uses LLM to draft a highly personalized proposal based on sales notes."""
    prompt = f"""
    Draft a sales proposal based on the following conversation notes.
    Company: {company} ({geography})
    Notes: {notes}
    Suggested Product: {lead_product_match}
    
    Extract the following and return as a JSON object:
    - stated_needs: (list of strings) The customer's stated needs.
    - has_budget_signal: (boolean) Whether budget was mentioned.
    - has_timeline: (boolean) Whether a timeline was mentioned.
    - constraints: (list of strings) Any constraints mentioned.
    - priority: (string) HIGH, MEDIUM, or LOW based on urgency/budget.
    - proposal_title: (string) A catchy title for the proposal.
    - proposal_summary: (string) A 2-sentence summary of the proposal.
    """
    
    response_text = generate(
        prompt=prompt,
        system_instruction="You are a top-tier B2B sales account executive. Always output valid JSON.",
        temperature=0.4
    )
    
    try:
        clean_json = response_text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception:
        # Return a failed parsing state
        return {
            "stated_needs": [],
            "has_budget_signal": False,
            "has_timeline": False,
            "constraints": [],
            "priority": "LOW",
            "proposal_title": f"Proposal: {company}",
            "proposal_summary": "Failed to generate AI proposal."
        }
