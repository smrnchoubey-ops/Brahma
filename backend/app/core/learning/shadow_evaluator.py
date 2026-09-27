"""
Shadow Deployment & Non-Authoritative Evaluation Engine
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Executes candidate patterns alongside baseline production models without altering
authoritative system state, capturing comparative performance evidence across
all 5 canonical Phase-5 learning categories (§17.3, §17.4, §19.5).
"""
from typing import Dict, Any, Optional, List, Callable, Tuple
from datetime import datetime, timezone
import time

from app.core.learning.models import LearningCandidate, ShadowEvaluationResult, PatternType, PatternStatus
from app.core.learning.verifiers import (
    IndependentCalculatorVerifier,
    IndependentToolRoutingVerifier,
    IndependentParameterAdaptationVerifier,
    IndependentRecoveryVerifier,
    IndependentHeuristicVerifier
)
from app.core.learning.policies import (
    IncumbentCalculatorBaselinePolicy,
    CalculatorCandidatePolicy,
    IncumbentToolRoutingBaselinePolicy,
    ToolRoutingCandidatePolicy,
    IncumbentParameterAdaptationBaselinePolicy,
    ParameterAdaptationCandidatePolicy,
    IncumbentRecoveryBaselinePolicy,
    RecoveryStrategyCandidatePolicy,
    IncumbentHeuristicBaselinePolicy,
    HeuristicRuleCandidatePolicy
)


class ShadowEvaluator:
    """
    Evaluates learning candidates in safe shadow mode against baseline task executions.
    """

    @classmethod
    def evaluate_shadow(
        cls,
        candidate: LearningCandidate,
        baseline_evaluator: Optional[Callable[[], Dict[str, Any]]] = None,
        candidate_evaluator: Optional[Callable[[], Dict[str, Any]]] = None
    ) -> ShadowEvaluationResult:
        """
        Executes baseline and candidate evaluators in isolated shadow mode.
        """
        # 1. Baseline Evaluation
        start_base = time.perf_counter()
        if baseline_evaluator:
            base_out = baseline_evaluator()
        else:
            base_out = {"success": True, "error": None}
        base_dur = (time.perf_counter() - start_base) * 1000.0

        # 2. Candidate Shadow Evaluation
        start_cand = time.perf_counter()
        if candidate_evaluator:
            cand_out = candidate_evaluator()
        else:
            cand_out = {"success": True, "error": None}
        cand_dur = (time.perf_counter() - start_cand) * 1000.0

        base_succ = 1.0 if base_out.get("success") else 0.0
        cand_succ = 1.0 if cand_out.get("success") else 0.0
        error_delta = 0.0 if cand_succ >= base_succ else (base_succ - cand_succ)

        # Shadow evaluation passes if candidate does not increase error rate
        passed = (cand_succ >= base_succ) and (error_delta == 0.0)

        return ShadowEvaluationResult(
            candidate_id=candidate.pattern_id,
            baseline_success_rate=base_succ,
            candidate_success_rate=cand_succ,
            baseline_latency_ms=round(base_dur, 2),
            candidate_latency_ms=round(cand_dur, 2),
            error_delta=round(error_delta, 4),
            passed=passed,
            evidence={
                "baseline_output": base_out,
                "candidate_output": cand_out,
                "shadow_mode": "NON_AUTHORITATIVE"
            }
        )

    @classmethod
    def _get_domain_evaluators(
        cls,
        candidate: LearningCandidate
    ) -> Tuple[Any, Any, Any]:
        """
        Returns (baseline_policy_cls, candidate_policy_instance, verifier_cls)
        for the given candidate's pattern_type.
        """
        ptype = candidate.pattern_type
        if ptype == PatternType.TOOL_ROUTING:
            return IncumbentToolRoutingBaselinePolicy, ToolRoutingCandidatePolicy(candidate), IndependentToolRoutingVerifier
        elif ptype == PatternType.PARAMETER_ADAPTATION:
            return IncumbentParameterAdaptationBaselinePolicy, ParameterAdaptationCandidatePolicy(candidate), IndependentParameterAdaptationVerifier
        elif ptype == PatternType.RECOVERY_STRATEGY:
            return IncumbentRecoveryBaselinePolicy, RecoveryStrategyCandidatePolicy(candidate), IndependentRecoveryVerifier
        elif ptype == PatternType.HEURISTIC_RULE:
            return IncumbentHeuristicBaselinePolicy, HeuristicRuleCandidatePolicy(candidate), IndependentHeuristicVerifier
        else:  # PLAN_OPTIMIZATION and default
            return IncumbentCalculatorBaselinePolicy, CalculatorCandidatePolicy(candidate), IndependentCalculatorVerifier

    @classmethod
    def evaluate_held_out_episodes(
        cls,
        candidate: LearningCandidate,
        held_out_episodes: List[Dict[str, Any]],
        baseline_evaluator: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        candidate_evaluator: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None
    ) -> Tuple[List[Dict[str, Any]], ShadowEvaluationResult]:
        """
        Executes same-episode comparative shadow evaluation across held-out task episodes (§17.3, §17.4).
        Both candidate and baseline receive the identical original episode input.
        """
        if not held_out_episodes:
            return [], cls.evaluate_shadow(candidate)

        eval_episodes = []
        base_successes = 0
        cand_successes = 0
        total_base_lat = 0.0
        total_cand_lat = 0.0
        comparative_provenance: List[Dict[str, Any]] = []

        base_policy_cls, cand_policy, verifier_cls = cls._get_domain_evaluators(candidate)

        for ep in held_out_episodes:
            # Enforce strict tenant boundary (§18.5)
            ep_tenant = ep.get("tenant_id")
            if ep_tenant and ep_tenant != candidate.tenant_id:
                raise ValueError(f"Cross-tenant evaluation episode rejected: '{ep_tenant}' != '{candidate.tenant_id}'.")

            expression = ep.get("expression") or ep.get("prompt") or ep.get("input") or ep.get("text")
            is_calculator_domain = (candidate.pattern_type == PatternType.PLAN_OPTIMIZATION) and (ep.get("tool") in ("calculator", "calculate") or expression is not None)

            # -------------------------------------------------------------
            # 1. Baseline Evaluation on Same Episode Input
            # -------------------------------------------------------------
            t0 = time.perf_counter()
            base_policy_id = getattr(base_policy_cls, "POLICY_ID", "policy:baseline:default")
            if baseline_evaluator:
                base_out = baseline_evaluator(ep)
                score_base = float(base_out.get("outcome_score", 1.0 if base_out.get("success") else 0.0))
                raw_base_res = base_out.get("result", base_out.get("output"))
                verifier_used = base_out.get("verifier_id", "custom_evaluator")
            elif expression and hasattr(base_policy_cls, "execute"):
                base_exec = base_policy_cls.execute(expression)
                base_policy_id = base_exec.get("policy_id", getattr(base_policy_cls, "POLICY_ID", "policy:baseline:default")) if isinstance(base_exec, dict) else getattr(base_policy_cls, "POLICY_ID", "policy:baseline:default")
                raw_base_res = base_exec.get("result", base_exec.get("output", base_exec)) if isinstance(base_exec, dict) else base_exec
                base_v = verifier_cls.verify(expression, raw_base_res)
                score_base = base_v.outcome_score
                verifier_used = base_v.verifier_id
                base_out = {
                    "success": (score_base == 1.0),
                    "outcome_score": score_base,
                    "result": raw_base_res,
                    "verifier_id": verifier_used
                }
            elif "outcome_score_baseline" in ep and ep["outcome_score_baseline"] is not None:
                score_base = float(ep["outcome_score_baseline"])
                raw_base_res = ep.get("result", ep.get("output"))
                verifier_used = ep.get("verifier_id", "pre_verified")
                base_out = {"success": (score_base == 1.0), "outcome_score": score_base}
            else:
                raise ValueError(f"Fail-closed: Episode {ep.get('task_id')} lacks genuine runtime baseline outcome score.")
            base_dur = (time.perf_counter() - t0) * 1000.0
            total_base_lat += base_dur

            # -------------------------------------------------------------
            # 2. Candidate Evaluation on Same Episode Input
            # -------------------------------------------------------------
            t1 = time.perf_counter()
            cand_policy_id = getattr(cand_policy, "policy_id", f"policy:candidate:{candidate.pattern_id}")
            if candidate_evaluator:
                cand_out = candidate_evaluator(ep)
                score_u = float(cand_out.get("outcome_score", 1.0 if cand_out.get("success") else 0.0))
                raw_cand_res = cand_out.get("result", cand_out.get("output"))
                cand_verifier_used = cand_out.get("verifier_id", "custom_evaluator")
            elif expression and hasattr(cand_policy, "execute"):
                cand_exec = cand_policy.execute(expression)
                cand_policy_id = cand_exec.get("policy_id", getattr(cand_policy, "policy_id", f"policy:candidate:{candidate.pattern_id}")) if isinstance(cand_exec, dict) else getattr(cand_policy, "policy_id", f"policy:candidate:{candidate.pattern_id}")
                raw_cand_res = cand_exec.get("result", cand_exec.get("output", cand_exec)) if isinstance(cand_exec, dict) else cand_exec
                cand_v = verifier_cls.verify(expression, raw_cand_res)
                score_u = cand_v.outcome_score
                cand_verifier_used = cand_v.verifier_id
                cand_out = {
                    "success": (score_u == 1.0),
                    "outcome_score": score_u,
                    "result": raw_cand_res,
                    "verifier_id": cand_verifier_used
                }
            elif "outcome_score_u" in ep and ep["outcome_score_u"] is not None:
                score_u = float(ep["outcome_score_u"])
                raw_cand_res = ep.get("result", ep.get("output"))
                cand_verifier_used = ep.get("verifier_id", "pre_verified")
                cand_out = {"success": (score_u == 1.0), "outcome_score": score_u}
            elif "outcome_score" in ep and ep["outcome_score"] is not None:
                score_u = float(ep["outcome_score"])
                raw_cand_res = ep.get("result", ep.get("output"))
                cand_verifier_used = ep.get("verifier_id", "pre_verified")
                cand_out = {"success": (score_u == 1.0), "outcome_score": score_u}
            else:
                raise ValueError(f"Fail-closed: Episode {ep.get('task_id')} lacks genuine runtime candidate outcome score.")
            cand_dur = (time.perf_counter() - t1) * 1000.0
            total_cand_lat += cand_dur

            if score_base == 1.0:
                base_successes += 1
            if score_u == 1.0:
                cand_successes += 1

            is_regression = (score_u < score_base)
            episode_delta = round(score_u - score_base, 4)

            eval_episodes.append({
                "task_id": ep.get("task_id"),
                "event_id": ep.get("event_id"),
                "tenant_id": candidate.tenant_id,
                "outcome_score_u": round(score_u, 4),
                "outcome_score_baseline": round(score_base, 4),
                "regression": is_regression,
                "is_held_out": True
            })

            comparative_provenance.append({
                "task_id": ep.get("task_id"),
                "event_id": ep.get("event_id"),
                "tenant_id": candidate.tenant_id,
                "expression": expression,
                "baseline_policy_id": base_policy_id,
                "candidate_policy_id": cand_policy_id,
                "baseline_raw_result": raw_base_res,
                "candidate_raw_result": raw_cand_res,
                "baseline_outcome_score": round(score_base, 4),
                "candidate_outcome_score": round(score_u, 4),
                "delta": episode_delta,
                "verifier_id": verifier_used,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
                "regression": is_regression
            })

        n = len(held_out_episodes)
        base_succ_rate = base_successes / n if n > 0 else 1.0
        cand_succ_rate = cand_successes / n if n > 0 else 1.0
        err_delta = max(0.0, base_succ_rate - cand_succ_rate)
        passed = (cand_succ_rate >= base_succ_rate) and (err_delta == 0.0)

        shadow_res = ShadowEvaluationResult(
            candidate_id=candidate.pattern_id,
            baseline_success_rate=round(base_succ_rate, 4),
            candidate_success_rate=round(cand_succ_rate, 4),
            baseline_latency_ms=round(total_base_lat / n, 2) if n > 0 else 0.0,
            candidate_latency_ms=round(total_cand_lat / n, 2) if n > 0 else 0.0,
            error_delta=round(err_delta, 4),
            passed=passed,
            evidence={
                "evaluated_episode_count": n,
                "shadow_mode": "NON_AUTHORITATIVE_HELD_OUT",
                "comparative_provenance": comparative_provenance
            }
        )
        return eval_episodes, shadow_res

    @classmethod
    def evaluate_live_shadow_event(
        cls,
        candidate: LearningCandidate,
        expression_or_input: str,
        baseline_output: Optional[Dict[str, Any]] = None,
        baseline_score: Optional[float] = None,
        task_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes a single live non-authoritative shadow evaluation pass on the incoming runtime task input.
        Guarantees candidate execution is fail-open and completely isolated from the primary authoritative result.
        """
        base_policy_cls, cand_policy, verifier_cls = cls._get_domain_evaluators(candidate)
        base_policy_id = getattr(base_policy_cls, "POLICY_ID", "policy:baseline:default")
        cand_policy_id = getattr(cand_policy, "policy_id", f"policy:candidate:{candidate.pattern_id}")

        # 1. Baseline Evaluation / Scoring
        if baseline_score is not None:
            score_base = float(baseline_score)
            raw_base_res = baseline_output
            verifier_used = getattr(verifier_cls, "VERIFIER_ID", "verifier:independent")
        elif baseline_output is not None:
            raw_base_res = baseline_output
            base_v = verifier_cls.verify(expression_or_input, raw_base_res)
            score_base = base_v.outcome_score
            verifier_used = base_v.verifier_id
        else:
            base_exec = base_policy_cls.execute(expression_or_input)
            base_policy_id = base_exec.get("policy_id", getattr(base_policy_cls, "POLICY_ID", "policy:baseline:default"))
            raw_base_res = base_exec
            base_v = verifier_cls.verify(expression_or_input, raw_base_res)
            score_base = base_v.outcome_score
            verifier_used = base_v.verifier_id

        # 2. Candidate Non-Authoritative Shadow Execution (Fail-Open)
        t1 = time.perf_counter()
        try:
            cand_exec = cand_policy.execute(expression_or_input)
            cand_policy_id = cand_exec.get("policy_id", getattr(cand_policy, "policy_id", f"policy:candidate:{candidate.pattern_id}"))
            raw_cand_res = cand_exec
            cand_v = verifier_cls.verify(expression_or_input, raw_cand_res)
            score_u = cand_v.outcome_score
        except Exception as ex:
            score_u = 0.0
            raw_cand_res = {"error": f"CANDIDATE_SHADOW_EXCEPTION: {str(ex)}"}
        cand_dur = (time.perf_counter() - t1) * 1000.0

        is_regression = (score_u < score_base)
        delta = round(score_u - score_base, 4)

        return {
            "task_id": task_id,
            "tenant_id": candidate.tenant_id,
            "pattern_id": candidate.pattern_id,
            "pattern_type": candidate.pattern_type.value,
            "expression": expression_or_input,
            "baseline_policy_id": base_policy_id,
            "candidate_policy_id": cand_policy_id,
            "baseline_raw_result": raw_base_res,
            "candidate_raw_result": raw_cand_res,
            "baseline_outcome_score": round(score_base, 4),
            "candidate_outcome_score": round(score_u, 4),
            "delta": delta,
            "candidate_duration_ms": round(cand_dur, 3),
            "verifier_id": verifier_used,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "regression": is_regression,
            "shadow_mode": "LIVE_NON_AUTHORITATIVE"
        }

    @classmethod
    def dispatch_live_shadow_evaluation(
        cls,
        task_id: int,
        user_id: Optional[int],
        tenant_id: str,
        prompt: str,
        execution_result: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Dispatches non-authoritative live shadow evaluation for all active SHADOW
        candidates matching the current tenant and classified task category.
        Uses an isolated database session and fail-open exception containment.
        """
        from app.db.database import SessionLocal
        from app.models.learning_pattern import LearningPattern
        from app.core.learning.ingestion import classify_task_category
        from app.repositories.chitra_repository import chitra_repository

        exec_res = execution_result if isinstance(execution_result, dict) else {}
        category = classify_task_category(prompt or "", exec_res)
        evaluations_recorded = []

        with SessionLocal() as db:
            try:
                shadow_patterns = db.query(LearningPattern).filter(
                    LearningPattern.tenant_id == tenant_id,
                    LearningPattern.status == "SHADOW",
                    LearningPattern.pattern_type == category.value
                ).all()

                if not shadow_patterns:
                    return []

                now_iso = datetime.now(timezone.utc).isoformat()

                for pat_row in shadow_patterns:
                    cand = LearningCandidate(
                        pattern_id=pat_row.pattern_id,
                        tenant_id=pat_row.tenant_id,
                        pattern_type=PatternType(pat_row.pattern_type),
                        name=pat_row.name,
                        description=pat_row.description,
                        action_template=pat_row.action_template or {},
                        confidence=pat_row.confidence,
                        status=PatternStatus.SHADOW,
                        metadata=dict(pat_row.metadata_payload or {})
                    )

                    prov = cls.evaluate_live_shadow_event(
                        candidate=cand,
                        expression_or_input=prompt,
                        baseline_output=exec_res,
                        task_id=task_id
                    )

                    evaluations_recorded.append(prov)

                    # Update persistent candidate metadata
                    meta = dict(pat_row.metadata_payload or {})
                    live_evals = meta.get("live_shadow_evaluations", [])
                    live_evals.append(prov)
                    meta["live_shadow_evaluations"] = live_evals
                    meta["shadow_eval_count"] = len(live_evals)
                    meta["last_shadow_eval_at"] = now_iso
                    if not meta.get("shadow_entered_at"):
                        meta["shadow_entered_at"] = pat_row.created_at.isoformat() if pat_row.created_at else now_iso

                    pat_row.metadata_payload = meta
                    pat_row.updated_at = datetime.now(timezone.utc)
                    db.commit()

                    # Log CHITRA shadow_evaluation audit record
                    try:
                        chitra_repository.append_event(
                            db=db,
                            task_id=task_id,
                            faculty="LEARNING",
                            event_type="shadow_evaluation",
                            decision={
                                "pattern_id": cand.pattern_id,
                                "tenant_id": cand.tenant_id,
                                "status": "SHADOW",
                                "comparative_provenance": [prov]
                            },
                            confidence=cand.confidence,
                            outcome=f"Live shadow evaluation for {cand.pattern_id}: delta={prov['delta']}, regression={prov['regression']}",
                            session_id=f"ses_shadow_{cand.pattern_id}",
                            user_id=user_id
                        )
                    except Exception as che:
                        import logging
                        logging.getLogger(__name__).warning(f"CHITRA shadow_evaluation event logging notice (fail-open): {che}")
            except Exception as e:
                # Fail-open guarantee: shadow processing failure never breaks anything
                import logging
                logging.getLogger(__name__).warning(f"Live shadow evaluation deferred: {e}")

        return evaluations_recorded
