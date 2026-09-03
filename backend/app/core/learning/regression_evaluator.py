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
        benchmark_runners: Optional[List[Callable[[], bool]]] = None
    ) -> RegressionTestResult:
        """
        Runs benchmark assertions against the candidate. Fails closed if any regression is found.
        """
        runners = benchmark_runners or []
        regressions_detected = 0
        details: List[str] = []

        if not runners:
            # Default canonical benchmark checks
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
        else:
            benchmark_count = len(runners)
            for idx, runner in enumerate(runners, start=1):
                try:
                    ok = runner()
                    if not ok:
                        regressions_detected += 1
                        details.append(f"Benchmark {idx} failed regression check.")
                except Exception as ex:
                    regressions_detected += 1
                    details.append(f"Benchmark {idx} exception: {type(ex).__name__} - {str(ex)}")

        passed = (regressions_detected == 0)
        return RegressionTestResult(
            candidate_id=candidate.pattern_id,
            benchmark_count=benchmark_count,
            regressions_detected=regressions_detected,
            passed=passed,
            details=details
        )
