from typing import Dict, Any
from agents.state import AgentState
from agents.execution import execute_action, ExecutionResult

def rachit_node(state: AgentState) -> Dict[str, Any]:
    print(f"[RACHIT] Execution triggered...")
    
    # 1. Enforce strict Maryada policy approval gate
    verdict = state.get("policy_verdict") or {}
    status = state.get("status")
    task_id = state.get("task_id")
    
    if verdict.get("approved") is not True or status == "MARYADA_BLOCKED":
        print(f"[RACHIT] ABORT: Execution triggered but policy was not approved!")
        if task_id:
            from app.services.audit_service import log_audit_event
            log_audit_event(
                task_id,
                "RACHIT",
                "Task Execution",
                "BLOCKED",
                {"reason": "Execution aborted due to missing policy approval."}
            )
        return {
            "current_agent": "RACHIT",
            "status": "RACHIT_BLOCKED",
            "execution_result": {
                "status": "BLOCKED",
                "reason": "Execution aborted due to missing policy approval."
            }
        }
        
    print(f"[RACHIT] Executing authorized action for plan: {state.get('plan', {}).get('summary', 'Unknown plan')}")
    
    # 2. Invoke real action executor via action router
    exec_result: ExecutionResult = execute_action(state)
    
    # 3. Log comprehensive, safe audit trail
    if task_id:
        from app.services.audit_service import log_audit_event
        mode = state.get("mode", "REACTIVE")
        audit_payload = {
            "action": exec_result.action_name,
            "status": exec_result.status,
            "mode": mode,
            "executed_at": exec_result.executed_at
        }
        if exec_result.output is not None:
            audit_payload["result"] = exec_result.output
        if exec_result.error:
            audit_payload["error"] = exec_result.error
            
        log_audit_event(
            task_id,
            "RACHIT",
            "Task Execution",
            exec_result.status,
            audit_payload
        )
    
    # 4. Return truthful execution state
    if exec_result.status == "EXECUTED":
        return {
            "current_agent": "RACHIT",
            "status": "RACHIT_EXECUTED",
            "execution_result": exec_result.model_dump()
        }
    elif exec_result.status == "BLOCKED":
        return {
            "current_agent": "RACHIT",
            "status": "RACHIT_BLOCKED",
            "execution_result": exec_result.model_dump()
        }
    else:  # FAILED
        return {
            "current_agent": "RACHIT",
            "status": "RACHIT_FAILED",
            "execution_result": exec_result.model_dump(),
            "errors": state.get("errors", []) + [f"RACHIT Execution Error: {exec_result.error}"]
        }
