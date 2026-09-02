import json
from typing import Dict, Any
from app.services.kosh_service import kosh
# pyrefly: ignore [missing-import]
from ..state import AgentState
from app.services.audit_service import log_audit_event

def kosh_node(state: AgentState) -> Dict[str, Any]:
    print(f"[KOSH] Retrieving knowledge context for intent...")
    
    if state.get("status") == "KARMA_FAILED" or state.get("errors"):
        return {
            "current_agent": "KOSH",
            "status": "KOSH_SKIPPED"
        }
        
    intent = state.get("intent", "")
    task_id = state.get("task_id")
    
    try:
        # Retrieve context from vector database
        results = kosh.retrieve(intent)
        
        context_str = ""
        if results:
            context_str = "Relevant Knowledge retrieved:\n"
            for res in results:
                context_str += f"- {res['title']}: {res['content']}\n"
        else:
            context_str = "No specific knowledge context found."
            
        if task_id:
            log_audit_event(task_id, "KOSH", "Context Retrieval", "SUCCESS", {"results_count": len(results) if results else 0})

        return {
            "current_agent": "KOSH",
            "status": "KOSH_SUCCESS",
            "knowledge_context": context_str
        }
    except Exception as e:
        print(f"[KOSH] Error retrieving knowledge: {str(e)}")
        if task_id:
            log_audit_event(task_id, "KOSH", "Context Retrieval", "FAILED", {"error": str(e)})

        # Safe failure: proceed without knowledge context
        return {
            "current_agent": "KOSH",
            "status": "KOSH_FAILED",
            "knowledge_context": "Knowledge retrieval failed. Proceeding without specific context.",
            "errors": state.get("errors", []) + [f"KOSH Error: {str(e)}"]
        }
