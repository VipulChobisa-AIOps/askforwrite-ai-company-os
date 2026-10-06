"""
Run the LangGraph Orchestrator with AI Agents
===============================================
Executes the newly built Manager -> Discovery -> Sales -> HITL loop.
"""

from pathlib import Path
from dotenv import load_dotenv

# Ensure environment is loaded before LangGraph/LangSmith initializes
env_file = Path(__file__).resolve().parent.parent / ".env"
if not env_file.exists():
    env_file = Path(__file__).resolve().parent / "os_gateway" / ".env"
load_dotenv(dotenv_path=env_file)
load_dotenv()

from app.agents.orchestrator import orchestrator_app


def run_orchestrator():
    print("--- Starting LangGraph Orchestrator ---")
    
    initial_state = {
        "task_id": "demo-task-001",
        "correlation_id": "demo-corr-001",
        "manager_id": "manager-1",
        "objective": "Find retail chains that need field force management",
        "limit": 5,
        "leads": [],
        "proposals": [],
        "pending_approvals": [],
        "approved_leads": [],
        "status": "PLANNING",
        "error": None,
    }
    
    # Stream the graph execution
    for output in orchestrator_app.stream(initial_state):
        for key, value in output.items():
            print(f"Node '{key}' executed. Current Status: {value.get('status')}")
            
            if key == "discovery_node":
                print(f"  -> Discovered {len(value.get('leads', []))} qualified leads using AI scoring.")
            
            if key == "sales_node":
                print(f"  -> Drafted {len(value.get('proposals', []))} proposals using AI sales agent.")
    
    print("\n--- Workflow Paused / Completed ---")
    print("Trace logged to your LangSmith project!")


if __name__ == "__main__":
    run_orchestrator()
