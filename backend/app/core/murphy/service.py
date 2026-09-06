"""
MURPHY Pre-flight Simulation Service & CHITRA Audit Integration
Strictly conforms to BRAHMA COS Whitesheet §11.0, §11.5 & §11.6.

Coordinates pre-flight plan simulation, tenant scoping, and appends canonical
CHITRA simulation audit records (faculty="MURPHY", event_type="simulation").
"""
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session

from app.core.karma.plan_dag import KarmaPlanDAG
from app.core.murphy.report import MurphyRiskReport, MurphyRiskTier, MurphyRecommendation
from app.core.murphy.simulator import MurphySimulationEngine
from app.repositories.chitra_repository import chitra_repository


class MurphyService:
    """
    High-level MURPHY Predictive Verification Service.
    """

    @classmethod
    def analyze_plan_risk(
        cls,
        plan: Optional[KarmaPlanDAG],
        tenant_id: str = "global",
        intent: Optional[str] = None,
        upstream_status: Optional[str] = None,
        upstream_errors: Optional[List[str]] = None,
        db_session: Optional[Session] = None,
        task_id: Optional[int] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> MurphyRiskReport:
        """
        Executes pre-flight adversarial simulation and records CHITRA simulation audit event.
        """
        if not tenant_id or not tenant_id.strip():
            raise ValueError("Authenticated Tenant ID is required for simulation.")

        # 1. Simulate Plan Risk (§11.1, §11.3, §11.5)
        report = MurphySimulationEngine.simulate_plan(
            plan=plan,
            intent=intent,
            upstream_status=upstream_status,
            upstream_errors=upstream_errors
        )

        # 2. Append CHITRA Simulation Audit Event (§11.6, §8.2)
        effective_task_id = task_id or (plan.task_id if plan else None)
        if db_session and effective_task_id:
            try:
                chitra_evt = chitra_repository.append_event(
                    db=db_session,
                    task_id=effective_task_id,
                    faculty="MURPHY",
                    event_type="simulation",
                    decision={
                        "risk_level": report.risk_level.value,
                        "blast_radius_score": report.blast_radius_score,
                        "failure_modes": report.failure_modes,
                        "security_concerns": report.security_concerns,
                        "recommendation": report.recommendation.value,
                        "simulated_steps_count": report.simulated_steps_count,
                        "tenant_id": tenant_id
                    },
                    confidence=1.0 if report.risk_level != MurphyRiskTier.UNKNOWN else 0.0,
                    outcome=f"Risk: {report.risk_level.value} (Blast Radius: {report.blast_radius_score})",
                    session_id=session_id or f"ses_murphy_{effective_task_id}",
                    user_id=user_id
                )
                report.chitra_event_id = chitra_evt.event_id
            except Exception:
                pass

        return report
