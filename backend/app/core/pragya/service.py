"""
PRAGYA Core Service & Faculty Orchestrator
Strictly conforms to BRAHMA COS Whitesheet §6.0–§6.6 & §15.0–§15.6.
"""
from typing import Dict, Any, Optional, List, Callable
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.karma.plan_dag import KarmaPlanDAG
from app.core.saga.models import SagaDefinition
from app.core.pragya.intent_parser import DeterministicIntentParser, IntentDecomposition
from app.core.pragya.plan_synthesizer import PragyaPlanSynthesizer
from app.core.pragya.validator import PragyaPlanValidator
from app.core.kosh.retrieval_service import KoshRetrievalService
from app.core.karma.tool_registry import KarmaToolRegistry
from app.repositories.chitra_repository import chitra_repository


class PragyaResult(BaseModel):
    """
    Formal structured outcome of PRAGYA cognitive reasoning & plan synthesis.
    """
    task_id: int
    tenant_id: str
    intent_decomposition: IntentDecomposition
    plan_dag: KarmaPlanDAG
    saga_definition: SagaDefinition
    knowledge_context_used: bool = False
    injected_chunk_count: int = 0
    chitra_event_id: Optional[str] = None
    is_valid: bool = True
    error: Optional[str] = None


class PragyaService:
    """
    Central cognitive orchestrator synthesizing validated Karma and Saga plans.
    """

    @classmethod
    def generate_plan(
        cls,
        intent: str,
        tenant_id: str,
        task_id: int,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        kosh_service: Optional[KoshRetrievalService] = None,
        tool_registry: Optional[KarmaToolRegistry] = None,
        llm_callable: Optional[Callable[[List[Dict[str, str]]], Any]] = None
    ) -> PragyaResult:
        """
        Translates raw user intent into formal, validated KarmaPlanDAG and SagaDefinition.
        """
        # 1. Intent Parsing & Validation (§6.1, §15.1)
        decomposition = DeterministicIntentParser.parse_intent(
            intent=intent,
            tenant_id=tenant_id,
            task_id=task_id,
            tool_registry=tool_registry
        )

        # 2. KOSH Memory Context Retrieval (§6.2, §15.2)
        knowledge_context = ""
        injected_count = 0
        if kosh_service:
            try:
                kosh_res = kosh_service.retrieve(
                    query=decomposition.main_goal,
                    tenant_id=tenant_id,
                    min_similarity=0.1,
                    db_session=db_session,
                    task_id=task_id,
                    user_id=user_id,
                    session_id=session_id
                )
                if kosh_res and kosh_res.chunks:
                    injected_count = len(kosh_res.chunks)
                    formatted_chunks = [c.get("content", "") for c in kosh_res.chunks if isinstance(c, dict)]
                    knowledge_context = "\n---\n".join(formatted_chunks)
            except Exception:
                # Graceful degradation on memory service issue
                knowledge_context = ""

        # 3. Plan & Saga Synthesis (§6.3, §15.3)
        plan_dag, saga_def = PragyaPlanSynthesizer.synthesize_plan(
            decomposition=decomposition,
            knowledge_context=knowledge_context,
            tool_registry=tool_registry,
            llm_callable=llm_callable
        )

        # 4. Final Validation (§6.4, §15.4)
        PragyaPlanValidator.validate_karma_dag(plan_dag, tool_registry=tool_registry)
        PragyaPlanValidator.validate_saga_definition(saga_def)

        # 5. CHITRA Plan Generation Audit Logging (§6.6, §15.6)
        chitra_event_id = None
        if db_session and task_id:
            try:
                chitra_evt = chitra_repository.append_event(
                    db=db_session,
                    task_id=task_id,
                    faculty="PRAGYA",
                    event_type="plan_generation",
                    decision={
                        "task_id": task_id,
                        "tenant_id": tenant_id,
                        "intent": decomposition.raw_intent,
                        "plan_summary": plan_dag.summary,
                        "step_count": len(plan_dag.steps),
                        "steps": [s.step_id for s in plan_dag.steps],
                        "tools_required": list(set(s.tool for s in plan_dag.steps)),
                        "knowledge_chunks_injected": injected_count
                    },
                    confidence=1.0,
                    outcome=f"Plan generated successfully with {len(plan_dag.steps)} steps",
                    session_id=session_id or f"ses_pragya_{task_id}",
                    user_id=user_id
                )
                chitra_event_id = chitra_evt.event_id
            except Exception:
                pass

        return PragyaResult(
            task_id=task_id,
            tenant_id=tenant_id,
            intent_decomposition=decomposition,
            plan_dag=plan_dag,
            saga_definition=saga_def,
            knowledge_context_used=bool(knowledge_context),
            injected_chunk_count=injected_count,
            chitra_event_id=chitra_event_id,
            is_valid=True
        )
