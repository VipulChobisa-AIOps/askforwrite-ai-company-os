"""
LangGraph Orchestrator for the AskforWrite AI Company OS.
=========================================================
State machine defining the Manager -> Specialist workflow with HITL gates.
"""

from typing import Literal, TypedDict

from langgraph.graph import START, StateGraph
from langsmith import traceable

from app.agents.ai_agents import ai_draft_proposal, ai_score_lead
from app.agents.sources import OfflineSignalProvider


class AgentState(TypedDict):
    """The state of the multi-agent workflow."""
    task_id: str
    correlation_id: str
    manager_id: str
    objective: str
    limit: int
    
    # Discovery output
    leads: list[dict]
    
    # Sales/Research output
    proposals: list[dict]
    
    # HITL Approvals
    pending_approvals: list[str]
    approved_leads: list[str]
    
    # Final status
    status: str
    error: str | None


@traceable(name="node_manager_plan")
def manager_plan_node(state: AgentState) -> dict:
    """Manager plans the objective."""
    return {"status": "PLANNING"}


@traceable(name="node_discovery")
def discovery_node(state: AgentState) -> dict:
    """Run Discovery and score leads using AI."""
    provider = OfflineSignalProvider()
    candidates = provider.search(state["objective"], limit=state["limit"])
    
    leads = []
    for candidate in candidates:
        if candidate.do_not_contact:
            continue
            
        # Call the AI scoring agent
        ai_score = ai_score_lead(candidate.company, candidate.signals)
        
        if ai_score["fit_score"] >= 0.30:
            leads.append({
                "company": candidate.company,
                "geography": candidate.geography,
                "product_match": ai_score["product_match"],
                "fit_score": ai_score["fit_score"],
                "reasoning": ai_score["reasoning"]
            })
            
    return {"leads": leads, "status": "DISCOVERED"}


@traceable(name="node_sales")
def sales_node(state: AgentState) -> dict:
    """Draft sales proposals for qualified leads using AI."""
    proposals = []
    for lead in state["leads"]:
        # Simulate notes from discovery/research
        notes = f"High potential for {lead['product_match']}. Reasoning: {lead['reasoning']}"
        
        # Call the AI sales agent
        draft = ai_draft_proposal(
            company=lead["company"],
            geography=lead["geography"],
            notes=notes,
            lead_product_match=lead["product_match"]
        )
        # Inject lead identity fields so UI and downstream consumers can identify the proposal
        draft["company"] = lead["company"]
        draft["geography"] = lead["geography"]
        draft["product_match"] = lead["product_match"]
        draft["fit_score"] = lead["fit_score"]
        # Normalise summary field name for GUI display
        draft["proposal_text"] = draft.get("proposal_summary", draft.get("proposal_title", ""))
        proposals.append(draft)
        
    return {"proposals": proposals, "status": "PROPOSED"}


@traceable(name="node_human_approval")
def human_approval_node(state: AgentState) -> dict:
    """Simulate a checkpoint for human approval."""
    # Collect company names awaiting sign-off so the GUI can display them
    pending = [
        p.get("company", "Unknown")
        for p in state.get("proposals", [])
    ]
    # In a real deployment with a LangGraph checkpointer this node would
    # interrupt execution and wait for the Owner API key decision endpoint.
    return {"status": "HUMAN_APPROVAL_REQUIRED", "pending_approvals": pending}


def router(state: AgentState) -> Literal["discovery_node", "sales_node", "human_approval_node", "__end__"]:
    """Route to the next node based on state."""
    status = state.get("status")
    if status == "PLANNING":
        return "discovery_node"
    elif status == "DISCOVERED":
        if state.get("leads"):
            return "sales_node"
        return "__end__"
    elif status == "PROPOSED":
        return "human_approval_node"
    elif status == "HUMAN_APPROVAL_REQUIRED":
        return "__end__"
    
    return "__end__"


# Build the Graph
workflow = StateGraph(AgentState)

workflow.add_node("manager_plan_node", manager_plan_node)
workflow.add_node("discovery_node", discovery_node)
workflow.add_node("sales_node", sales_node)
workflow.add_node("human_approval_node", human_approval_node)

workflow.add_edge(START, "manager_plan_node")
workflow.add_conditional_edges("manager_plan_node", router)
workflow.add_conditional_edges("discovery_node", router)
workflow.add_conditional_edges("sales_node", router)
workflow.add_conditional_edges("human_approval_node", router)

# Compile the graph
orchestrator_app = workflow.compile()
