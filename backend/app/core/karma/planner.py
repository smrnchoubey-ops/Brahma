"""
KARMA Planner Integration
Conforms to BRAHMA COS Whitesheet §7.2.

Decomposes PRAGYA reasoning output into formal, validated KARMA Plan DAGs.
"""
from typing import Dict, Any, Union, List
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep, KarmaRetryPolicy


def build_karma_plan_from_pragya(
    pragya_plan: Any,
    task_id: int,
    default_authority: str = "LOW"
) -> KarmaPlanDAG:
    """
    Transforms PRAGYA reasoning output (dict or Pydantic PragyaPlan) into a formal,
    validated KarmaPlanDAG with explicit step nodes, dependencies, and retry policies.
    """
    if not pragya_plan:
        raise ValueError("Cannot build KARMA Plan DAG from empty PRAGYA output.")

    # Extract summary and raw steps
    if isinstance(pragya_plan, dict):
        summary = pragya_plan.get("summary", "Automated Task Plan")
        raw_steps = pragya_plan.get("steps", [])
        tools_needed = pragya_plan.get("tools_needed", [])
        assumptions = pragya_plan.get("assumptions", [])
    else:
        summary = getattr(pragya_plan, "summary", "Automated Task Plan")
        raw_steps = getattr(pragya_plan, "steps", [])
        tools_needed = getattr(pragya_plan, "tools_needed", [])
        assumptions = getattr(pragya_plan, "assumptions", [])

    if not raw_steps:
        # Fallback single step
        raw_steps = ["Execute task objective"]

    karma_steps: List[KarmaStep] = []
    
    for idx, step_item in enumerate(raw_steps):
        step_id = f"step_{idx + 1}"
        
        # Determine tool assignment
        tool_name = "generic_executor"
        if idx < len(tools_needed) and tools_needed[idx]:
            tool_name = tools_needed[idx]
        elif tools_needed:
            tool_name = tools_needed[0]

        if isinstance(step_item, dict):
            action_desc = step_item.get("action", f"Execute action {idx + 1}")
            expected_outcome = step_item.get("expected_outcome", f"Action {idx + 1} completed successfully")
            dependencies = step_item.get("dependencies", [f"step_{idx}"] if idx > 0 else [])
            authority = step_item.get("authority_required", default_authority)
            reason = step_item.get("reason", f"Required step for task {task_id}")
            tool = step_item.get("tool", tool_name)
        else:
            action_desc = str(step_item)
            expected_outcome = f"Outcome achieved: {action_desc[:60]}"
            # Sequential pipeline dependency by default
            dependencies = [f"step_{idx}"] if idx > 0 else []
            authority = default_authority
            reason = f"Execution step {idx + 1} derived from PRAGYA decision"
            tool = tool_name

        karma_steps.append(
            KarmaStep(
                step_id=step_id,
                action=action_desc,
                tool=tool,
                reason=reason,
                expected_outcome=expected_outcome,
                dependencies=dependencies,
                retry_policy=KarmaRetryPolicy(),
                authority_required=authority
            )
        )

    return KarmaPlanDAG(
        task_id=task_id,
        summary=summary,
        steps=karma_steps,
        assumptions=assumptions or []
    )
