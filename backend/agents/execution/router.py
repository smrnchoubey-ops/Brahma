import re
from typing import Dict, Any, Tuple, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from .registry import (
    ACTION_REGISTRY,
    DISALLOWED_TOOL_KEYWORDS,
    ExecutionError,
    ActionSecurityError
)

class ExecutionResult(BaseModel):
    status: str = Field(description="One of: EXECUTED, BLOCKED, FAILED")
    action_name: str
    output: Optional[Any] = None
    error: Optional[str] = None
    executed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

def _resolve_action_and_params(state: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Deterministically resolves which permitted action to execute and extracts its parameters
    from the approved plan and intent.
    """
    plan = state.get("plan") or {}
    intent = str(state.get("intent", "")).lower()
    summary = str(plan.get("summary", "")).lower()
    tools_needed = [str(t).lower().strip() for t in plan.get("tools_needed", [])]
    
    # 1. First: Check for explicitly disallowed dangerous tools in plan
    for tool in tools_needed:
        for blocked in DISALLOWED_TOOL_KEYWORDS:
            if re.search(rf"\b{re.escape(blocked)}\b", tool):
                raise ActionSecurityError(f"Action '{tool}' violates security policy (Disallowed keyword: '{blocked}').")
                
    # Also check raw intent for obvious malicious attempts trying to bypass to Rachit
    for blocked in ["format drive", "rm -rf", "drop table", "powershell", "subprocess"]:
        if blocked in intent:
            raise ActionSecurityError(f"Security violation: dangerous command detected in request ('{blocked}').")

    # 2. Check if a known registered tool was explicitly listed in tools_needed
    for tool in tools_needed:
        for reg_name in ACTION_REGISTRY:
            if reg_name in tool or tool in reg_name:
                return reg_name, _extract_params_for_action(reg_name, state)

    # 3. Keyword / Intent Matching for Registered Harmless Tools
    # Calculate / Math
    if any(k in intent or k in summary for k in ["calculate", "math", "add", "sum", "multiply", "divide"]):
        return "calculate", _extract_params_for_action("calculate", state)
        
    # Calendar / Holidays
    if any(k in intent or k in summary for k in ["calendar", "holiday", "leave schedule", "vacation"]):
        return "calendar_lookup", _extract_params_for_action("calendar_lookup", state)
        
    # System Status / Telemetry
    if any(k in intent or k in summary for k in ["system status", "health check", "diagnostic", "server status"]):
        return "system_status", _extract_params_for_action("system_status", state)
        
    # Policy Lookup
    if any(k in intent or k in summary for k in ["policy", "guideline", "rule", "timesheet", "backup"]):
        return "policy_lookup", _extract_params_for_action("policy_lookup", state)

    # Echo / Formatting
    if any(k in intent or k in summary for k in ["format text", "uppercase", "lowercase", "echo"]):
        return "echo", _extract_params_for_action("echo", state)
        
    # Default fallback for approved plans: summarize deliverable
    return "deliverable_summary", _extract_params_for_action("deliverable_summary", state)

def _extract_params_for_action(action_name: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Safely extracts parameter mappings from state for a given action."""
    intent = state.get("intent", "")
    plan = state.get("plan") or {}
    
    if action_name == "calculate":
        return {"expression": intent}
    elif action_name == "calendar_lookup":
        # Check if year is mentioned
        year_match = re.search(r"\b(202[0-9])\b", intent)
        year = int(year_match.group(1)) if year_match else 2026
        return {"year": year}
    elif action_name == "policy_lookup":
        return {"topic": intent}
    elif action_name == "system_status":
        return {"scope": "standard"}
    elif action_name == "echo":
        fmt = "plain"
        if "uppercase" in intent.lower():
            fmt = "uppercase"
        elif "lowercase" in intent.lower():
            fmt = "lowercase"
        elif "bullet" in intent.lower():
            fmt = "bulleted"
        return {"text": intent, "format": fmt}
    elif action_name == "deliverable_summary":
        return {
            "plan_summary": plan.get("summary", "Plan executed successfully."),
            "steps": plan.get("steps", [])
        }
    return {}

def execute_action(state: Dict[str, Any]) -> ExecutionResult:
    """
    Validates policy approval, resolves the authorized action from registry,
    and executes it safely.
    """
    # Verify Policy Approval
    verdict = state.get("policy_verdict") or {}
    if verdict.get("approved") is not True:
        return ExecutionResult(
            status="BLOCKED",
            action_name="none",
            error="Execution aborted: MARYADA policy approval is False or missing."
        )

    try:
        action_name, params = _resolve_action_and_params(state)
    except ActionSecurityError as se:
        return ExecutionResult(
            status="BLOCKED",
            action_name="security_gate",
            error=str(se)
        )
    except Exception as e:
        return ExecutionResult(
            status="FAILED",
            action_name="resolver",
            error=f"Failed to resolve action: {str(e)}"
        )

    action_meta = ACTION_REGISTRY.get(action_name)
    if not action_meta:
        return ExecutionResult(
            status="FAILED",
            action_name=action_name,
            error=f"Unregistered action requested: '{action_name}'"
        )

    handler = action_meta["handler"]
    try:
        output = handler(params)
        return ExecutionResult(
            status="EXECUTED",
            action_name=action_name,
            output=output
        )
    except ExecutionError as ee:
        return ExecutionResult(
            status="FAILED",
            action_name=action_name,
            error=str(ee)
        )
    except Exception as ex:
        return ExecutionResult(
            status="FAILED",
            action_name=action_name,
            error=f"Unexpected action execution error: {str(ex)}"
        )
