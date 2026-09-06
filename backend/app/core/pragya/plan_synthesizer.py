"""
PRAGYA Structured Plan Synthesizer & DAG Formulation Engine
Strictly conforms to BRAHMA COS Whitesheet §6.3, §6.4, §15.3 & §15.4.
"""
from typing import Dict, Any, Optional, List, Callable, Tuple
import json
import re
from pydantic import BaseModel, Field

from app.core.llm import call_llm
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep, KarmaRetryPolicy
from app.core.saga.models import SagaDefinition, SagaStep
from app.core.saga.service import SagaService
from app.core.pragya.intent_parser import IntentDecomposition
from app.core.pragya.validator import PragyaPlanValidator, PragyaPlanValidationError
from app.core.karma.tool_registry import KarmaToolRegistry


class StructuredStepDraft(BaseModel):
    """
    Intermediate schema for steps parsed from LLM reasoning.
    """
    step_id: str
    action: str
    tool: str = "generic_executor"
    reason: str = ""
    expected_outcome: str = "Success"
    dependencies: List[str] = Field(default_factory=list)
    authority_required: str = "LOW"
    compensating_action: Optional[str] = None


class StructuredPlanDraft(BaseModel):
    """
    Structured plan envelope parsed from LLM structured JSON response.
    """
    summary: str
    assumptions: List[str] = Field(default_factory=list)
    steps: List[StructuredStepDraft]


class PragyaPlanSynthesizer:
    """
    Synthesizes formal KarmaPlanDAG and SagaDefinition workflows from Intent and KOSH context.
    """

    @classmethod
    def synthesize_plan(
        cls,
        decomposition: IntentDecomposition,
        knowledge_context: Optional[str] = None,
        tool_registry: Optional[KarmaToolRegistry] = None,
        llm_callable: Optional[Callable[[List[Dict[str, str]]], Any]] = None
    ) -> Tuple[KarmaPlanDAG, SagaDefinition]:
        """
        Synthesizes both KarmaPlanDAG and SagaDefinition from intent and memory context.
        """
        registry = tool_registry or KarmaToolRegistry()
        known_tools = [f"{t.tool_id}: {t.description} (caps: {', '.join(t.capabilities)})" for t in registry.list_tools()]
        tools_str = "\n".join(known_tools) if known_tools else "generic_executor: Generic safe sandbox execution"

        # 1. Construct Prompt
        system_prompt = f"""You are PRAGYA, the deterministic cognitive reasoning engine of BRAHMA COS.
Your goal is to formulate a structured execution DAG plan to achieve the user's intent.

SYSTEM CONSTRAINTS & INVARIANTS:
1. Every step must have a unique 'step_id' (e.g. 'step_1', 'step_2').
2. 'dependencies' must list prerequisite step_ids. The graph MUST be a valid Directed Acyclic Graph (NO CYCLES).
3. 'expected_outcome' must define declarative success criteria.
4. 'compensating_action' must specify the inverse action to roll back changes if this step succeeds but later steps fail.
5. 'authority_required' must be one of: 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'.

AVAILABLE REGISTERED TOOLS:
{tools_str}

REQUIRED JSON SCHEMA:
{StructuredPlanDraft.model_json_schema()}

Respond ONLY with valid, unescaped JSON matching this schema."""

        user_content = f"""USER INTENT:
{decomposition.raw_intent}

SUB-GOALS:
{decomposition.sub_goals}

EXPLICIT CONSTRAINTS:
{json.dumps(decomposition.constraints)}

KOSH KNOWLEDGE CONTEXT:
{knowledge_context or 'None available.'}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]

        # 2. Invoke LLM or Injected Callable
        try:
            if llm_callable:
                resp_content = llm_callable(messages)
            else:
                llm_resp = call_llm(messages=messages, temperature=0.0)
                resp_content = llm_resp.choices[0].message.content

            # 3. Parse & Clean JSON
            plan_draft = cls._parse_and_validate_json(resp_content, decomposition)
        except Exception:
            plan_draft = cls._build_deterministic_fallback_plan(decomposition)

        # 4. Construct KarmaPlanDAG
        karma_steps: List[KarmaStep] = []
        for s in plan_draft.steps:
            karma_steps.append(KarmaStep(
                step_id=s.step_id,
                action=s.action,
                tool=s.tool,
                reason=s.reason,
                expected_outcome=s.expected_outcome,
                dependencies=s.dependencies,
                retry_policy=KarmaRetryPolicy(max_attempts=3),
                authority_required=s.authority_required
            ))

        karma_dag = KarmaPlanDAG(
            task_id=decomposition.task_id,
            summary=plan_draft.summary,
            steps=karma_steps,
            assumptions=plan_draft.assumptions or decomposition.assumptions
        )

        # 5. Construct SagaDefinition
        saga_steps: List[SagaStep] = []
        for s in plan_draft.steps:
            saga_steps.append(SagaStep(
                step_id=s.step_id,
                forward_action=s.action,
                compensating_action=s.compensating_action,
                dependencies=s.dependencies,
                metadata={"tool": s.tool, "authority": s.authority_required}
            ))

        saga_def = SagaService.create_saga(
            task_id=decomposition.task_id,
            tenant_id=decomposition.tenant_id,
            summary=plan_draft.summary,
            steps=saga_steps,
            metadata={"source": "PRAGYA_SYNTHESIZER", "intent": decomposition.raw_intent}
        )

        # 6. Validate Output
        PragyaPlanValidator.validate_karma_dag(karma_dag, tool_registry=registry)
        PragyaPlanValidator.validate_saga_definition(saga_def)

        return karma_dag, saga_def

    @classmethod
    def _parse_and_validate_json(cls, raw_content: str, decomposition: IntentDecomposition) -> StructuredPlanDraft:
        """
        Strips markdown wrapping and parses JSON into StructuredPlanDraft fail-closed.
        """
        if not raw_content or not raw_content.strip():
            raise PragyaPlanValidationError("LLM returned empty response.")

        content = raw_content.strip()
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()

        try:
            parsed = json.loads(content)
            return StructuredPlanDraft.model_validate(parsed)
        except Exception as ex:
            # Fallback deterministic builder from sub-goals if syntax error
            return cls._build_deterministic_fallback_plan(decomposition)

    @classmethod
    def _build_deterministic_fallback_plan(cls, decomposition: IntentDecomposition) -> StructuredPlanDraft:
        """
        Synthesizes a clean deterministic linear plan directly from parsed intent sub-goals.
        """
        steps: List[StructuredStepDraft] = []
        prev_step_id: Optional[str] = None

        for idx, subgoal in enumerate(decomposition.sub_goals, start=1):
            s_id = f"step_{idx}"
            deps = [prev_step_id] if prev_step_id else []
            steps.append(StructuredStepDraft(
                step_id=s_id,
                action=subgoal,
                tool="generic_executor",
                reason=f"Fulfill sub-goal {idx}",
                expected_outcome=f"Completed {subgoal}",
                dependencies=deps,
                authority_required="HIGH" if decomposition.constraints.get("elevated_risk") else "LOW",
                compensating_action=f"revert_{subgoal.replace(' ', '_')}"
            ))
            prev_step_id = s_id

        return StructuredPlanDraft(
            summary=f"Deterministic plan for: {decomposition.main_goal}",
            assumptions=decomposition.assumptions,
            steps=steps
        )
