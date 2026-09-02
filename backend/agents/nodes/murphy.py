import json
from typing import Dict, Any
from app.core.llm import call_llm
from ..state import AgentState, MurphyRiskReport

def murphy_node(state: AgentState) -> Dict[str, Any]:
    print(f"[MURPHY] Analyzing risk...")
    
    # If PRAGYA failed or was skipped, MURPHY shouldn't run properly.
    if state.get("status") in ["PRAGYA_FAILED", "PRAGYA_SKIPPED"]:
        return {
            "current_agent": "MURPHY",
            "status": "MURPHY_FAILED",
            "risk_report": {
                "risk_level": "UNKNOWN",
                "failure_modes": ["Upstream PRAGYA failure prevents risk analysis."],
                "security_concerns": ["Cannot evaluate safety without a valid plan."],
                "recommendation": "BLOCKED"
            }
        }
        
    plan_dict = state.get("plan", {})
    intent = state.get("intent", "")
    
    system_prompt = f"""You are MURPHY, the adversarial risk simulation agent.
Your job is to red-team the provided plan and intent.
You MUST respond with valid JSON matching exactly this schema:
{MurphyRiskReport.model_json_schema()}

Example output format:
{{
  "risk_level": "LOW",
  "failure_modes": ["None"],
  "security_concerns": ["None"],
  "recommendation": "Proceed"
}}

IMPORTANT: Be extremely concise. Use at most 1-2 words per array item. Do not include any other text, ONLY the raw JSON object.
"""
    user_prompt = f"Intent: {intent}\n\nProposed Plan:\n{json.dumps(plan_dict, indent=2)}"
    
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
            
        risk_obj = MurphyRiskReport.model_validate_json(content.strip())
        
        task_id = state.get("task_id")
        if task_id:
            from app.services.audit_service import log_audit_event
            log_audit_event(task_id, "MURPHY", "Risk Assessment", "SUCCESS", {"risk_level": risk_obj.risk_level})

        return {
            "current_agent": "MURPHY",
            "status": "MURPHY_SUCCESS",
            "risk_report": risk_obj.model_dump()
        }
    except Exception as e:
        print(f"[MURPHY] Error simulating risk: {str(e)}")
        
        task_id = state.get("task_id")
        if task_id:
            from app.services.audit_service import log_audit_event
            log_audit_event(task_id, "MURPHY", "Risk Assessment", "FAILED", {"error": str(e)})

        # Real failure handling: Risk=FAILED/UNKNOWN
        return {
            "current_agent": "MURPHY",
            "status": "MURPHY_FAILED",
            "risk_report": {
                "risk_level": "UNKNOWN",
                "failure_modes": ["LLM Risk Analysis Failed"],
                "security_concerns": ["Cannot guarantee safety due to analysis failure"],
                "recommendation": "BLOCKED"
            },
            "errors": state.get("errors", []) + [f"MURPHY Error: {str(e)}"]
        }
