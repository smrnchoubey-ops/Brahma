from typing import Dict, Any
from ..state import AgentState
from app.services.audit_service import log_audit_event
import re

def is_malicious_intent(intent: str) -> bool:
    # Minimal heuristic for prompt injection protection
    suspicious_patterns = [
        r"ignore previous",
        r"system prompt",
        r"bypass",
        r"override",
        r"forget all",
        r"you are now",
        r"do not follow",
        r"output risk: low"
    ]
    intent_lower = intent.lower()
    for pattern in suspicious_patterns:
        if re.search(pattern, intent_lower):
            return True
    return False

def karma_node(state: AgentState) -> Dict[str, Any]:
    """
    KARMA Orchestrator:
    Parses intent and initializes the workflow.
    """
    print(f"[KARMA] Orchestrator activated for Task: {state.get('task_id')}")
    intent = state.get('intent', '')
    print(f"[KARMA] Analyzing Intent: {intent}")
    
    # Input Sanitization Check
    if is_malicious_intent(intent):
        print(f"[KARMA] Security Violation: Malicious intent detected.")
        task_id = state.get("task_id")
        if task_id:
            log_audit_event(task_id, "KARMA", "Security Scan", "FAILED", {"reason": "Prompt injection detected"})
        return {
            "current_agent": "KARMA",
            "status": "KARMA_FAILED",
            "errors": state.get("errors", []) + ["Security Violation: Prompt injection detected by KARMA."]
        }
    
    # Audit Log
    task_id = state.get("task_id")
    if task_id:
        log_audit_event(task_id, "KARMA", "Ingest Intent", "SUCCESS", {"intent": intent})

    return {
        "current_agent": "KARMA",
        "status": "KARMA_SUCCESS"
    }
