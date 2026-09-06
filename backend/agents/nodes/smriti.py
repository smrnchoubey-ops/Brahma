from typing import Dict, Any
from app.core.smriti.service import smriti_service
from ..state import AgentState


def smriti_node(state: AgentState) -> Dict[str, Any]:
    """
    SMRITI Runtime Node (Whitesheet §4.1 Path 2, §5 F5 Temporal Memory).
    Enforces tenant boundaries, loads prior session continuity context from PostgreSQL,
    and durably persists the current user interaction.
    """
    print(f"[SMRITI] Loading session continuity and recording interaction...")

    # 1. Skip on upstream failure
    if state.get("status") == "KARMA_FAILED" or state.get("errors"):
        return {
            "current_agent": "SMRITI",
            "status": "SMRITI_SKIPPED"
        }

    tenant_id = state.get("tenant_id")
    session_id = state.get("session_id")
    task_id = state.get("task_id")
    user_id = state.get("user_id")
    intent = state.get("intent", "")

    # 2. Fail-closed on missing or empty tenant_id (CA-008)
    if not tenant_id or not str(tenant_id).strip():
        print(f"[SMRITI] Security Violation: Missing tenant_id in runtime state.")
        return {
            "current_agent": "SMRITI",
            "status": "SMRITI_FAILED",
            "errors": state.get("errors", []) + ["Security Violation: SMRITI aborted because tenant_id is missing (fail-closed)."]
        }

    clean_tenant_id = str(tenant_id).strip()

    try:
        # 3. Load PRIOR session continuity BEFORE persisting current interaction
        prior_records = []
        if session_id and str(session_id).strip():
            prior_records = smriti_service.load_session_context(
                tenant_id=clean_tenant_id,
                session_id=str(session_id).strip()
            )

        if prior_records:
            context_lines = [f"- ({r.source}): {r.content}" for r in prior_records]
            memory_context = "Prior Session Continuity:\n" + "\n".join(context_lines)
        else:
            memory_context = "No prior session continuity found."

        # 4. Persist current interaction only according to SMRITI contract
        if intent and intent.strip():
            smriti_service.record_interaction(
                tenant_id=clean_tenant_id,
                content=intent.strip(),
                user_id=user_id,
                session_id=str(session_id).strip() if session_id else None,
                task_id=task_id,
                memory_type="conversation",
                source="user"
            )

        return {
            "current_agent": "SMRITI",
            "status": "SMRITI_SUCCESS",
            "memory_context": memory_context
        }

    except Exception as e:
        print(f"[SMRITI] Error in session continuity: {str(e)}")
        return {
            "current_agent": "SMRITI",
            "status": "SMRITI_FAILED",
            "errors": state.get("errors", []) + [f"SMRITI Error: {str(e)}"]
        }
