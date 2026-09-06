from typing import Dict, Any
from app.core.kosh.service import kosh_service
from ..state import AgentState
from app.services.audit_service import log_audit_event

def kosh_node(state: AgentState) -> Dict[str, Any]:
    print(f"[KOSH] Retrieving active knowledge context for intent...")
    
    if state.get("status") in ["KARMA_FAILED", "SMRITI_FAILED", "SMRITI_SKIPPED"] or state.get("errors"):
        return {
            "current_agent": "KOSH",
            "status": "KOSH_SKIPPED"
        }
        
    intent = state.get("intent", "")
    task_id = state.get("task_id")
    user_id = state.get("user_id")
    tenant_id = state.get("tenant_id")

    # Fail-closed on missing or empty tenant_id (CA-008)
    if not tenant_id or not str(tenant_id).strip():
        print(f"[KOSH] Security Violation: Missing tenant_id in runtime state.")
        return {
            "current_agent": "KOSH",
            "status": "KOSH_FAILED",
            "errors": state.get("errors", []) + ["Security Violation: KOSH aborted because tenant_id is missing (fail-closed)."]
        }

    clean_tenant_id = str(tenant_id).strip()

    try:
        # Retrieve ACTIVE knowledge only from PostgreSQL scoped to tenant
        results = kosh_service.query_active_knowledge(
            tenant_id=clean_tenant_id,
            query_text=intent.strip() if intent else None,
            user_id=None
        )
        
        context_str = ""
        if results:
            context_str = "Relevant Knowledge retrieved (ACTIVE):\n"
            for res in results:
                context_str += f"- {res.title} (Provenance: {res.provenance_source}, Confidence: {res.confidence_score:.2f}): {res.content}\n"
        else:
            context_str = "No specific active knowledge context found."
            
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

        # Fail closed on system/query errors
        return {
            "current_agent": "KOSH",
            "status": "KOSH_FAILED",
            "knowledge_context": "Knowledge retrieval failed.",
            "errors": state.get("errors", []) + [f"KOSH Error: {str(e)}"]
        }
