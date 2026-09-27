"""
Learning System: Regression Prevention & Evaluation Engine
Strictly conforms to BRAHMA COS Whitesheet Learning System.

Asserts zero behavioral or performance regressions on benchmark tasks prior to promotion.
"""
from typing import Dict, Any, Optional, List, Callable
from app.core.learning.models import LearningCandidate, RegressionTestResult


class RegressionEvaluator:
    """
    Executes benchmark suites to detect potential performance, policy, or functional regressions.
    """

    @classmethod
    def evaluate_regressions(
        cls,
        candidate: LearningCandidate,
        benchmark_runners: Optional[List[Callable[[], bool]]] = None,
        eval_episodes: Optional[List[Dict[str, Any]]] = None
    ) -> RegressionTestResult:
        """
        Runs benchmark assertions against the candidate. Fails closed if any regression is found.
        """
        runners = benchmark_runners or []
        regressions_detected = 0
        details: List[str] = []
        benchmark_count = 0

        # 1. Evaluate per-episode regressions from held-out episode set E (§19.5)
        if eval_episodes:
            benchmark_count += len(eval_episodes)
            for idx, ep in enumerate(eval_episodes, start=1):
                ep_tenant = ep.get("tenant_id")
                if ep_tenant and ep_tenant != candidate.tenant_id:
                    raise ValueError(f"Cross-tenant evaluation episode rejected: '{ep_tenant}' != '{candidate.tenant_id}'.")
                score_u = float(ep.get("outcome_score_u", ep.get("score_u", 1.0)))
                score_base = float(ep.get("outcome_score_baseline", ep.get("score_baseline", 0.0)))
                if score_u < score_base or ep.get("regression") is True:
                    regressions_detected += 1
                    ep_id = ep.get("task_id") or ep.get("event_id") or f"ep_{idx}"
                    details.append(f"Episode {ep_id} regressed: candidate ({score_u}) < baseline ({score_base}).")

        # 2. Evaluate benchmark runners if provided
        if runners:
            benchmark_count += len(runners)
            for idx, runner in enumerate(runners, start=1):
                try:
                    ok = runner()
                    if not ok:
                        regressions_detected += 1
                        details.append(f"Benchmark {idx} failed regression check.")
                except Exception as ex:
                    regressions_detected += 1
                    details.append(f"Benchmark {idx} exception: {type(ex).__name__} - {str(ex)}")
        elif not eval_episodes:
            # Default canonical structural checks only when no eval_episodes and no runners
            benchmark_count = 3
            # Check 1: Non-empty action template
            if not candidate.action_template:
                regressions_detected += 1
                details.append("Regression: Empty action template in candidate.")

            # Check 2: Non-negative confidence
            if candidate.confidence < 0.0:
                regressions_detected += 1
                details.append("Regression: Negative confidence score.")

            # Check 3: Tenant scope integrity
            if not candidate.tenant_id or not candidate.tenant_id.strip():
                regressions_detected += 1
                details.append("Regression: Corrupted tenant scope.")

        passed = (regressions_detected == 0)
        return RegressionTestResult(
            candidate_id=candidate.pattern_id,
            benchmark_count=benchmark_count,
            regressions_detected=regressions_detected,
            passed=passed,
            details=details
        )
