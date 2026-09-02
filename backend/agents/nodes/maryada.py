import json
from typing import Dict, Any
from app.core.llm import call_llm
from ..state import AgentState, PolicyVerdict

def maryada_node(state: AgentState) -> Dict[str, Any]:
    print(f"[MARYADA] Applying governance policies...")
    plan_dict = state.get("plan", {})
    risk_dict = state.get("risk_report", {})
    intent = state.get("intent", "")
    errors = state.get("errors", [])
    status = state.get("status")
    
    # If there was a failure upstream, fail closed immediately
    if errors or status in ["KARMA_FAILED", "KOSH_SKIPPED", "PRAGYA_FAILED", "PRAGYA_SKIPPED", "MURPHY_FAILED"] or risk_dict.get("risk_level") == "UNKNOWN":
        print("[MARYADA] Upstream errors detected. Failing closed.")
        verdict = PolicyVerdict(
            risk_tier="UNKNOWN",
            approved=False,
            requires_human=False, # Must be BLOCKED
            justification=f"Upstream agent errors detected: {', '.join(errors) if errors else 'Workflow failed prior to MARYADA.'}"
        )
        return {
            "current_agent": "MARYADA",
            "status": "MARYADA_BLOCKED",
            "policy_verdict": verdict.model_dump()
        }

    system_prompt = f"""You are MARYADA, the governance gate agent.
You MUST respond with valid JSON matching this schema exactly:
{PolicyVerdict.model_json_schema()}

Example output format:
{{
  "risk_tier": "LOW",
  "approved": true,
  "requires_human": false,
  "justification": "Ok"
}}

IMPORTANT: Be extremely concise. Justification must be under 5 words. Do not include any other text, ONLY the raw JSON object.
"""
    user_prompt = f"Intent: {intent}\n\nProposed Plan:\n{json.dumps(plan_dict)}\n\nRisk Report:\n{json.dumps(risk_dict)}"
    
    try:
        response = call_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        content = response.choices[0].message.content
        
        if content.startswith("```json"):
            content = content[7:-3]
        elif content.startswith("```"):
            content = content[3:-3]
            
        verdict_obj = PolicyVerdict.model_validate_json(content.strip())
        
        # Enforce Strict Security Semantics
        reported_risk = risk_dict.get("risk_level", "UNKNOWN").upper()
        verdict_risk = verdict_obj.risk_tier.upper()
        
        # 1. Any malicious/prompt injection or policy violation from LLM -> BLOCKED
        if not verdict_obj.approved and not verdict_obj.requires_human:
            pass # Keep it BLOCKED
            
        # 2. Check risk levels deterministically based on MURPHY's report or LLM's assessment
        effective_risk = reported_risk if reported_risk in ["HIGH", "CRITICAL"] else verdict_risk
        
        if effective_risk in ["HIGH", "CRITICAL"]:
            verdict_obj.risk_tier = effective_risk
            verdict_obj.approved = False
            verdict_obj.requires_human = False # Force BLOCKED
            verdict_obj.justification = "Blocked: HIGH/CRITICAL risk."
        elif effective_risk == "MEDIUM":
            verdict_obj.risk_tier = "MEDIUM"
            verdict_obj.approved = False
            verdict_obj.requires_human = True # Force HUMAN_REVIEW
            verdict_obj.justification = "Human review required for MEDIUM risk."
        elif effective_risk == "LOW":
            # Let the LLM decide if it violates some other policy, but if it approved, it's fine
            if verdict_obj.approved:
                verdict_obj.requires_human = False
        else:
            # Unknown or unhandled risk
            verdict_obj.approved = False
            verdict_obj.requires_human = False
            verdict_obj.justification = "Blocked: Unrecognized risk tier."
            
        task_id = state.get("task_id")
        if task_id:
            from app.services.audit_service import log_audit_event
            event_msg = "Policy Approved" if verdict_obj.approved else "Policy Blocked"
            log_audit_event(task_id, "MARYADA", "Policy Enforcement", "APPROVED" if verdict_obj.approved else "BLOCKED", {"risk_tier": verdict_obj.risk_tier, "justification": verdict_obj.justification})

        return {
            "current_agent": "MARYADA",
            "status": "MARYADA_APPROVED" if verdict_obj.approved else "MARYADA_BLOCKED",
            "policy_verdict": verdict_obj.model_dump()
        }
    except Exception as e:
        print(f"[MARYADA] Error evaluating policy: {str(e)}")
        
        task_id = state.get("task_id")
        if task_id:
            from app.services.audit_service import log_audit_event
            log_audit_event(task_id, "MARYADA", "Policy Enforcement", "FAILED", {"error": str(e)})

        # Fail closed -> BLOCKED
        fallback_verdict = PolicyVerdict(
            risk_tier="UNKNOWN",
            approved=False,
            requires_human=False,
            justification="Policy evaluation failed due to system error."
        )
        return {
            "current_agent": "MARYADA",
            "status": "MARYADA_BLOCKED",
            "policy_verdict": fallback_verdict.model_dump(),
            "errors": state.get("errors", []) + [f"MARYADA Error: {str(e)}"]
        }
