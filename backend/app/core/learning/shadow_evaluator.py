"""
Shadow Deployment & Non-Authoritative Evaluation Engine
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Executes candidate patterns alongside baseline production models without altering
authoritative system state, capturing comparative performance evidence.
"""
from typing import Dict, Any, Optional, List, Callable
import time

from app.core.learning.models import LearningCandidate, ShadowEvaluationResult


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
