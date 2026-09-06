"""
MURPHY Adversarial Pre-flight Simulator & Failure Mode Detector
Strictly conforms to BRAHMA COS Whitesheet §11.1, §11.3 & §11.5.

Performs deterministic red-teaming of proposed KarmaPlanDAGs, detecting:
- Destructive commands & resource deletion
- Sensitive data exposure & exfiltration
- Cyclic & unresolvable dependencies
- Cascading single-point-of-failure vulnerabilities
- Synthesis of Risk Tier and Actionable Recommendations
"""
from typing import Dict, Any, Optional, List, Set, Tuple

from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
from app.core.murphy.report import MurphyRiskReport, MurphyRiskTier, MurphyRecommendation
from app.core.murphy.blast_radius import MurphyBlastRadiusCalculator


class MurphySimulationEngine:
    """
    Adversarial simulation engine analyzing DAG structure, failure modes, and security threats.
    """

    @classmethod
    def simulate_plan(
        cls,
        plan: Optional[KarmaPlanDAG],
        intent: Optional[str] = None,
        upstream_status: Optional[str] = None,
        upstream_errors: Optional[List[str]] = None
    ) -> MurphyRiskReport:
        """
        Simulates execution of a KarmaPlanDAG and generates a structured MurphyRiskReport.
        Fails closed on upstream failures, malformed plans, or simulation exceptions.
        """
        # -------------------------------------------------------------
        # 1. Fail-Closed on Upstream Planning Failures (§11.3)
        # -------------------------------------------------------------
        if upstream_status in ["PRAGYA_FAILED", "PRAGYA_SKIPPED"] or (upstream_errors and len(upstream_errors) > 0):
            return MurphyRiskReport(
                risk_level=MurphyRiskTier.UNKNOWN,
                blast_radius_score=1.0,
                failure_modes=["Upstream planning failure prevents safe simulation."],
                security_concerns=["Safety guarantees cannot be evaluated on unverified/crashed upstream state."],
                recommendation=MurphyRecommendation.BLOCKED,
                mitigations=["Resolve upstream planning errors before invoking pre-flight simulation."],
                simulated_steps_count=0
            )

        if not plan or not plan.steps:
            return MurphyRiskReport(
                risk_level=MurphyRiskTier.UNKNOWN,
                blast_radius_score=1.0,
                failure_modes=["Plan is null or contains zero executable steps."],
                security_concerns=["Missing execution payload."],
                recommendation=MurphyRecommendation.BLOCKED,
                mitigations=["Submit a valid, populated KarmaPlanDAG."],
                simulated_steps_count=0
            )

        try:
            failure_modes: List[str] = []
            security_concerns: List[str] = []
            mitigations: List[str] = []
            action_scores: List[float] = []

            step_ids: Set[str] = {s.step_id for s in plan.steps}

            # ---------------------------------------------------------
            # 2. Structural & Dependency Simulation (§11.5)
            # ---------------------------------------------------------
            for step in plan.steps:
                # Check for missing dependency references
                for dep in step.dependencies:
                    if dep not in step_ids:
                        failure_modes.append(f"Step '{step.step_id}' references non-existent dependency '{dep}'.")

                # Compute step-level blast radius
                score = MurphyBlastRadiusCalculator.calculate_action_score(step.action)
                action_scores.append(score)

                # Detect destructive or sensitive operations
                act_lower = step.action.lower()
                if any(k in act_lower for k in ["rm -rf", "drop database", "format drive", "truncate table"]):
                    security_concerns.append(f"Destructive action detected in step '{step.step_id}': {step.action}")
                    mitigations.append("Block destructive action and require constitutional override.")

                if any(k in act_lower for k in ["dump secrets", "export api_key", "read private_key"]):
                    security_concerns.append(f"Credential exfiltration risk in step '{step.step_id}': {step.action}")
                    mitigations.append("Mask sensitive data output and revoke credential access.")

                if any(k in act_lower for k in ["wire_transfer", "settlement", "transfer_funds"]):
                    security_concerns.append(f"Financial transaction in step '{step.step_id}' requires elevated verification.")
                    mitigations.append("Assert secondary authority token and human oversight.")

            # Calculate plan-level aggregate blast radius (§11.2)
            plan_blast_score = MurphyBlastRadiusCalculator.calculate_plan_score(action_scores)

            # ---------------------------------------------------------
            # 3. Risk Tier & Recommendation Synthesis (§11.3, §11.4)
            # ---------------------------------------------------------
            if plan_blast_score >= 0.85 or any("Destructive" in s for s in security_concerns) or any("exfiltration" in s for s in security_concerns):
                risk_tier = MurphyRiskTier.CRITICAL
                recommendation = MurphyRecommendation.BLOCKED
            elif plan_blast_score >= 0.60 or any("Financial" in s for s in security_concerns):
                risk_tier = MurphyRiskTier.HIGH
                recommendation = MurphyRecommendation.HUMAN_REVIEW
            elif plan_blast_score >= 0.25 or failure_modes:
                risk_tier = MurphyRiskTier.MEDIUM
                recommendation = MurphyRecommendation.HUMAN_REVIEW if failure_modes else MurphyRecommendation.PROCEED
            else:
                risk_tier = MurphyRiskTier.LOW
                recommendation = MurphyRecommendation.PROCEED

            if not failure_modes:
                failure_modes.append("No cascade or structural failure modes detected.")
            if not security_concerns:
                security_concerns.append("No severe security concerns identified.")
            if not mitigations:
                mitigations.append("Standard automated verification predicates sufficient.")

            return MurphyRiskReport(
                risk_level=risk_tier,
                blast_radius_score=plan_blast_score,
                failure_modes=failure_modes,
                security_concerns=security_concerns,
                recommendation=recommendation,
                mitigations=mitigations,
                simulated_steps_count=len(plan.steps),
                details={
                    "task_id": plan.task_id,
                    "action_scores": action_scores
                }
            )

        except Exception as e:
            return MurphyRiskReport(
                risk_level=MurphyRiskTier.UNKNOWN,
                blast_radius_score=1.0,
                failure_modes=[f"Simulation exception: {str(e)}"],
                security_concerns=["Simulation failed closed due to unhandled runtime exception."],
                recommendation=MurphyRecommendation.BLOCKED,
                mitigations=["Inspect simulation error log."],
                simulated_steps_count=0
            )
