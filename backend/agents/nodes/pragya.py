import json
from typing import Dict, Any
from app.core.llm import call_llm
from ..state import AgentState, PragyaPlan

def pragya_node(state: AgentState) -> Dict[str, Any]:
    print(f"[PRAGYA] Reasoning over intent...")
    
    if state.get("status") in ["KARMA_FAILED", "SMRITI_FAILED", "SMRITI_SKIPPED", "KOSH_FAILED", "KOSH_SKIPPED"] or state.get("errors"):
        return {
            "current_agent": "PRAGYA",
            "status": "PRAGYA_SKIPPED"
        }
        
    intent = state.get("intent", "")
    
    system_prompt = f"""You are PRAGYA, the core reasoning agent of BRAHMA COS.
Your goal is to formulate a structured plan to address the user's intent.
You MUST respond with valid JSON matching exactly this schema:
{PragyaPlan.model_json_schema()}

Example output format:
{{
  "summary": "Brief summary of the plan",
  "steps": ["Step 1", "Step 2"],
  "tools_needed": ["tool1", "tool2"],
  "assumptions": ["assumption1"]
}}
Do not include any other text, markdown blocks, or chain-of-thought in your response, ONLY the raw JSON object.
"""
    
    memory = state.get("memory_context", "")
    knowledge = state.get("knowledge_context", "")
    user_prompt = f"Intent: {intent}\n\nMemory Continuity:\n{memory}\n\nKnowledge Context:\n{knowledge}"
    
    try:
        response = call_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        content = response.choices[0].message.content
        
        # Strip markdown if present
        if content.startswith("```json"):
            content = content[7:-3]
        elif content.startswith("```"):
            content = content[3:-3]
            
        plan_obj = PragyaPlan.model_validate_json(content.strip())
        
        task_id = state.get("task_id")
        if task_id:
            from app.services.audit_service import log_audit_event
            log_audit_event(task_id, "PRAGYA", "Plan Generation", "SUCCESS", {"plan_summary": plan_obj.summary})

        return {
            "current_agent": "PRAGYA",
            "status": "PRAGYA_SUCCESS",
            "plan": plan_obj.model_dump()
        }
    except Exception as e:
        print(f"[PRAGYA] Error generating plan: {str(e)}")
        
        task_id = state.get("task_id")
        if task_id:
            from app.services.audit_service import log_audit_event
            log_audit_event(task_id, "PRAGYA", "Plan Generation", "FAILED", {"error": str(e)})

        # Safe failure - TRUTHFUL STATE
        return {
            "current_agent": "PRAGYA",
            "status": "PRAGYA_FAILED",
            "errors": state.get("errors", []) + [f"PRAGYA Error: {str(e)}"]
        }
