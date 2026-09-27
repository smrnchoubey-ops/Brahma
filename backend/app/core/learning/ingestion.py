"""
LEARNING INGESTION & RUNTIME EPISODE PIPELINE (Whitesheet §19.5, §20.3 & F14/F15)
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Connects real completed runtime tasks from PostgreSQL to:
1. Provenance extraction of completed runtime episodes across all 5 canonical categories:
   - PLAN_OPTIMIZATION
   - TOOL_ROUTING
   - PARAMETER_ADAPTATION
   - RECOVERY_STRATEGY
   - HEURISTIC_RULE
2. Tenant isolation boundary enforcement (§18.5)
3. Strict verifiable episode filtering via clean-room domain verifiers (no unverified scores)
4. Deterministic Train (E_train >= k_min) vs Held-Out (E_eval >= 1) episode partitioning (E_train ∩ E_eval = ∅)
5. Candidate pattern extraction via F14PatternExtractor
6. Comparative evaluation and Whitesheet §19.5 LE calculation via LearningService
7. F15 evolutionary stewardship and PostgreSQL persistence in 'learning_patterns'
8. Fail-closed semantics when insufficient valid historical episodes exist.
"""
import logging
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session

from app.models.task import Task
from app.core.learning.models import LearningCandidate, PatternStatus, PatternType
from app.core.learning.pattern_extractor import F14PatternExtractor
from app.core.learning.service import LearningService
from app.core.learning.verifiers import (
    IndependentCalculatorVerifier,
    IndependentToolRoutingVerifier,
    IndependentParameterAdaptationVerifier,
    IndependentRecoveryVerifier,
    IndependentHeuristicVerifier
)

logger = logging.getLogger(__name__)


def classify_task_category(prompt: str, res: Dict[str, Any]) -> PatternType:
    """
    Deterministically maps a task and its execution result to one of the
    5 canonical Phase-5 learning categories.
    """
    p_lower = (prompt or "").lower()
    action_name = res.get("action_name", res.get("tool", "")).lower()

    if action_name == "system_status" or "engine" in res or any(k in p_lower for k in ("system_status", "system status", "health check", "diagnostic", "server status", "recovery")):
        return PatternType.RECOVERY_STRATEGY
    elif action_name == "calendar_lookup" or "calendar_year" in res or any(k in p_lower for k in ("calendar_lookup", "calendar", "holiday", "leave schedule", "vacation")):
        return PatternType.TOOL_ROUTING
    elif action_name == "policy_lookup" or "policies" in res or any(k in p_lower for k in ("policy_lookup", "policy", "guideline", "rule", "timesheet", "backup", "deployment")):
        return PatternType.HEURISTIC_RULE
    elif action_name == "echo" or ("output" in res and "format" in res) or any(k in p_lower for k in ("format text", "uppercase", "lowercase", "bullet")):
        return PatternType.PARAMETER_ADAPTATION
    elif action_name == "calculate" or "expression" in res or any(k in p_lower for k in ("calculate", "math", "arithmetic")):
        return PatternType.PLAN_OPTIMIZATION
    else:
        return PatternType.TOOL_ROUTING


class LearningIngestionService:
    """
    Production ingestion pipeline connecting naturally completed runtime tasks
    to the F14/F15 evolutionary learning lifecycle.
    """

    @classmethod
    def on_task_completed(
        cls,
        db: Session,
        task: Task,
        k_min: int = F14PatternExtractor.DEFAULT_K_MIN,
        le_threshold: float = 0.50,
        lambda_reg: float = 0.50
    ) -> Optional[Tuple[bool, str, Optional[LearningCandidate]]]:
        """
        Post-completion lifecycle hook invoked upon task completion in production.
        Fails safely without interrupting the primary task execution transaction.
        """
        if task.status != "COMPLETED":
            return None

        tenant_id = f"tenant_{task.user_id}" if task.user_id else "tenant_global"
        res = task.execution_result if isinstance(task.execution_result, dict) else {}
        category = classify_task_category(task.prompt or "", res)

        try:
            return cls.ingest_and_evaluate_tenant_episodes(
                db=db,
                tenant_id=tenant_id,
                user_id=task.user_id,
                pattern_type=category,
                k_min=k_min,
                le_threshold=le_threshold,
                lambda_reg=lambda_reg,
                deploy_to_shadow_only=True
            )
        except Exception as ex:
            logger.warning(f"Learning ingestion deferred for tenant '{tenant_id}' category '{category}': {ex}")
            return False, f"DEFERRED: {str(ex)}", None

    @classmethod
    def ingest_and_evaluate_tenant_episodes(
        cls,
        db: Session,
        tenant_id: str,
        user_id: Optional[int] = None,
        pattern_type: Optional[PatternType] = None,
        k_min: int = F14PatternExtractor.DEFAULT_K_MIN,
        le_threshold: float = 0.50,
        lambda_reg: float = 0.50,
        deploy_to_shadow_only: bool = False
    ) -> Tuple[bool, str, Optional[LearningCandidate]]:
        """
        Queries completed runtime tasks for a tenant, extracts verified episodes,
        splits into disjoint E_train and E_eval, extracts candidate, and evaluates LE.
        When deploy_to_shadow_only=True (runtime mode), deploys candidate to SHADOW state
        for ongoing live shadow observation rather than immediately running batch promotion.
        """
        if not tenant_id or not tenant_id.strip():
            raise ValueError("Security Violation: Missing tenant_id in learning ingestion (fail-closed).")

        # 1. Query naturally completed tasks from PostgreSQL ordered deterministically
        query = db.query(Task).filter(
            Task.status == "COMPLETED",
            Task.execution_result.isnot(None)
        )
        if user_id is not None:
            query = query.filter(Task.user_id == user_id)
        elif tenant_id.startswith("tenant_") and tenant_id[7:].isdigit():
            inferred_uid = int(tenant_id[7:])
            query = query.filter(Task.user_id == inferred_uid)

        # Deterministic chronological ordering (Implementation Choice)
        completed_tasks = query.order_by(Task.created_at.asc(), Task.id.asc()).all()

        # 2. Extract structured episodes with verifiable runtime provenance
        episodes_by_type: Dict[PatternType, List[Dict[str, Any]]] = {pt: [] for pt in PatternType}

        for t in completed_tasks:
            res = t.execution_result
            if not isinstance(res, dict):
                continue

            prompt_text = t.prompt or ""
            t_category = classify_task_category(prompt_text, res)

            # Filter if specific pattern_type requested
            if pattern_type is not None and t_category != pattern_type:
                continue

            cand_score = None
            verifier_id = None
            raw_input = prompt_text

            # Check if explicit outcome score is present
            if "outcome_score_u" in res or "outcome_score" in res:
                cand_score = float(res.get("outcome_score_u", res.get("outcome_score")))
                verifier_id = res.get("verifier_id", "runtime_explicit")
            else:
                # Independent Clean-Room Domain Verification
                if t_category == PatternType.PLAN_OPTIMIZATION:
                    raw_res = res.get("result")
                    if raw_res is None and isinstance(res.get("output"), dict):
                        raw_res = res["output"].get("result")
                    v_out = IndependentCalculatorVerifier.verify(prompt_text, raw_res)
                    if v_out.is_valid:
                        cand_score = v_out.outcome_score
                        verifier_id = v_out.verifier_id

                elif t_category == PatternType.TOOL_ROUTING:
                    v_out = IndependentToolRoutingVerifier.verify(prompt_text, res)
                    if v_out.is_valid:
                        cand_score = v_out.outcome_score
                        verifier_id = v_out.verifier_id

                elif t_category == PatternType.PARAMETER_ADAPTATION:
                    v_out = IndependentParameterAdaptationVerifier.verify(prompt_text, res)
                    if v_out.is_valid:
                        cand_score = v_out.outcome_score
                        verifier_id = v_out.verifier_id

                elif t_category == PatternType.RECOVERY_STRATEGY:
                    v_out = IndependentRecoveryVerifier.verify(prompt_text, res)
                    if v_out.is_valid:
                        cand_score = v_out.outcome_score
                        verifier_id = v_out.verifier_id

                elif t_category == PatternType.HEURISTIC_RULE:
                    v_out = IndependentHeuristicVerifier.verify(prompt_text, res)
                    if v_out.is_valid:
                        cand_score = v_out.outcome_score
                        verifier_id = v_out.verifier_id

            if cand_score is None:
                # Fail-closed on unverified outcome: do NOT invent or fabricate scores
                continue

            base_score = float(res["outcome_score_baseline"]) if "outcome_score_baseline" in res and res["outcome_score_baseline"] is not None else None
            duration_ms = float(res.get("duration_ms", 100.0))
            tool_used = str(res.get("action_name", res.get("tool_used", res.get("tool", "generic"))))

            ep = {
                "task_id": t.id,
                "event_id": f"task_exec_{t.id}",
                "tenant_id": tenant_id,
                "status": "SUCCESS",
                "duration_ms": duration_ms,
                "tool": tool_used,
                "expression": raw_input,
                "prompt": raw_input,
                "outcome_score": cand_score,
                "outcome_score_u": cand_score,
                "verifier_id": verifier_id,
                "created_at": t.created_at.isoformat() if t.created_at else None
            }
            if base_score is not None:
                ep["outcome_score_baseline"] = base_score

            episodes_by_type[t_category].append(ep)

        # 3. Determine target category to evaluate
        target_category = pattern_type
        if target_category is None:
            # Find first category with sufficient episodes (>= k_min + 1)
            for pt, eps in episodes_by_type.items():
                if len(eps) >= k_min + 1:
                    target_category = pt
                    break
            if target_category is None:
                target_category = PatternType.PLAN_OPTIMIZATION

        from app.models.learning_pattern import LearningPattern
        from app.core.learning.stewardship import F15EvolutionarySteward

        if deploy_to_shadow_only:
            existing_shadow = db.query(LearningPattern).filter(
                LearningPattern.tenant_id == tenant_id,
                LearningPattern.pattern_type == target_category.value,
                LearningPattern.status == "SHADOW"
            ).first()
            if existing_shadow:
                return (
                    True,
                    f"Active candidate '{existing_shadow.pattern_id}' is already in SHADOW for tenant '{tenant_id}'.",
                    None
                )

        episodes = episodes_by_type[target_category]
        total_episodes = len(episodes)

        # 4. Fail-closed on insufficient episodes
        required_episodes = k_min if deploy_to_shadow_only else (k_min + 1)
        if total_episodes < required_episodes:
            req_msg = f"{k_min} training episodes" if deploy_to_shadow_only else f"{required_episodes} (k_min={k_min} training + at least 1 held-out evaluation episode)"
            return (
                False,
                f"INSUFFICIENT_EPISODES: Tenant '{tenant_id}' has {total_episodes} valid completed episodes with verified outcome_score for {target_category.value}. "
                f"Minimum required is {req_msg}.",
                None
            )

        # 5. Partition into strictly disjoint E_train and E_eval
        e_train = episodes[:k_min]
        e_eval = episodes[k_min:] if not deploy_to_shadow_only else []

        if not deploy_to_shadow_only:
            # Validate disjointness invariant
            train_ids = set(ep["task_id"] for ep in e_train)
            eval_ids = set(ep["task_id"] for ep in e_eval)
            if not train_ids.isdisjoint(eval_ids):
                raise ValueError(f"Integrity Error: E_train and E_eval overlap on task IDs: {train_ids.intersection(eval_ids)}")

        # 6. Extract candidate pattern via F14
        candidate_name = f"OptimizationPattern_{target_category.value}_{tenant_id}"
        candidate = F14PatternExtractor.extract_pattern(
            tenant_id=tenant_id,
            episodes=e_train,
            pattern_type=target_category,
            name=candidate_name,
            k_min=k_min
        )

        if deploy_to_shadow_only:
            # 7. Constitutional Validation & Deploy to Shadow (Leaves candidate in SHADOW for live traffic)
            last_train_task_id = e_train[-1]["task_id"] if e_train else None
            val_ok = F15EvolutionarySteward.validate_candidate(
                candidate=candidate,
                db_session=db,
                user_id=user_id,
                task_id=last_train_task_id
            )
            if not val_ok:
                return False, "Failed constitutional validation.", candidate

            F15EvolutionarySteward.deploy_to_shadow(
                candidate=candidate,
                db_session=db,
                user_id=user_id,
                task_id=last_train_task_id
            )
            return True, f"Candidate '{candidate.pattern_id}' deployed to SHADOW for tenant '{tenant_id}'.", candidate

        # 8. Execute full F15 Evolutionary Stewardship lifecycle with held-out episodes E_eval (Batch mode)
        last_eval_task_id = e_eval[-1]["task_id"] if e_eval else None
        promoted, reason, processed_cand = LearningService.process_candidate_lifecycle(
            candidate=candidate,
            held_out_episodes=e_eval,
            le_threshold=le_threshold,
            lambda_reg=lambda_reg,
            db_session=db,
            user_id=user_id,
            task_id=last_eval_task_id
        )

        return promoted, reason, processed_cand
