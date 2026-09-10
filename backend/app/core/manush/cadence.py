"""
PERIODIC HUMAN OVERSIGHT CADENCE TRACKER
Strictly conforms to BRAHMA COS Whitesheet:
- §3.3 Operational Modes (Autonomous Execution Scoping)
- §12.5 Cadence Tiers & Periodic Oversight (Oversight in Batches)
- Appendix A / CP-203 Oversight Cadence Defaults (N=50 actions OR T=30 minutes, whichever first)
- §23 Phase 6 Autonomous Operations Exit Criteria

Implements periodic oversight cadence for low-risk AUTONOMOUS mode operations.
Periodic cadence acts as a batched review record (non-blocking audit checkpoint),
working additively alongside real-time (per-decision) MARYADA constitutional gating.
"""
import os
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone
from enum import Enum
import logging
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.task import Task
from app.repositories.chitra_repository import chitra_repository

logger = logging.getLogger(__name__)


class CadenceTriggerReason(str, Enum):
    NONE = "NONE"
    ACTION_BOUNDARY = "ACTION_BOUNDARY"          # Reached N actions boundary (Default N=50)
    TIME_BOUNDARY = "TIME_BOUNDARY"              # Reached T time boundary (Default T=30 minutes)
    BOTH_BOUNDARIES = "BOTH_BOUNDARIES"          # Reached both N actions and T time


class TenantCadenceState:
    """Maintains in-memory action counter, timestamp, and recent action batch per tenant/session."""
    def __init__(self, tenant_id: str, session_id: Optional[str] = None):
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.action_count: int = 0
        self.interval_start: datetime = datetime.now(timezone.utc)
        self.recent_actions: List[Dict[str, Any]] = []
        self.last_checkpoint_at: Optional[datetime] = None
        self.total_checkpoints_triggered: int = 0

    def reset_interval(self, current_time: Optional[datetime] = None):
        """Resets interval counters following a successful periodic checkpoint."""
        now = current_time or datetime.now(timezone.utc)
        self.action_count = 0
        self.interval_start = now
        self.recent_actions = []
        self.last_checkpoint_at = now
        self.total_checkpoints_triggered += 1


class CadenceEvaluationResult(BaseModel):
    """Evaluation output of autonomous oversight cadence check."""
    triggered: bool
    reason: CadenceTriggerReason
    actions_executed: int
    elapsed_minutes: float
    threshold_actions: int
    threshold_minutes: float
    tenant_id: str
    session_id: Optional[str] = None
    evaluated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PeriodicOversightCadenceTracker:
    """
    Manages Periodic oversight cadence per Whitesheet §12.5 and CP-203.
    Tracks AUTONOMOUS mode actions per tenant/session and records canonical
    periodic oversight checkpoints in CHITRA when thresholds are reached.
    """
    # Whitesheet CP-203 canonical production defaults: N=50 actions or T=30 minutes
    DEFAULT_MAX_ACTIONS: int = 50
    DEFAULT_MAX_MINUTES: float = 30.0

    def __init__(
        self,
        default_max_actions: Optional[int] = None,
        default_max_minutes: Optional[float] = None
    ):
        # Allow environment variable override, constructor override, or fallback to CP-203 defaults
        env_actions = os.getenv("OVERSIGHT_CADENCE_MAX_ACTIONS")
        env_minutes = os.getenv("OVERSIGHT_CADENCE_MAX_MINUTES")

        self.max_actions: int = (
            default_max_actions
            if default_max_actions is not None
            else (int(env_actions) if env_actions is not None else self.DEFAULT_MAX_ACTIONS)
        )
        self.max_minutes: float = (
            default_max_minutes
            if default_max_minutes is not None
            else (float(env_minutes) if env_minutes is not None else self.DEFAULT_MAX_MINUTES)
        )

        # In-memory tenant/session cadence registry
        self._registry: Dict[str, TenantCadenceState] = {}

    def _get_or_create_state(self, tenant_id: str, session_id: Optional[str] = None) -> TenantCadenceState:
        key = tenant_id
        if key not in self._registry:
            self._registry[key] = TenantCadenceState(tenant_id=tenant_id, session_id=session_id)
        return self._registry[key]

    def reset_tracker(self):
        """Clears in-memory tracker state (used between isolated test suites)."""
        self._registry.clear()

    def evaluate_cadence(
        self,
        tenant_id: str,
        session_id: Optional[str] = None,
        current_time: Optional[datetime] = None,
        max_actions: Optional[int] = None,
        max_minutes: Optional[float] = None
    ) -> CadenceEvaluationResult:
        """
        Evaluates whether an autonomous operational stream has reached periodic review boundary.
        Thresholds: N actions (default 50) OR T minutes (default 30.0 min), whichever occurs first (CP-203).
        """
        threshold_n = max_actions if max_actions is not None else self.max_actions
        threshold_t = max_minutes if max_minutes is not None else self.max_minutes

        state = self._get_or_create_state(tenant_id=tenant_id, session_id=session_id)
        now = current_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if state.interval_start.tzinfo is None:
            state.interval_start = state.interval_start.replace(tzinfo=timezone.utc)

        elapsed_seconds = max(0.0, (now - state.interval_start).total_seconds())
        elapsed_minutes = elapsed_seconds / 60.0

        action_triggered = state.action_count >= threshold_n
        time_triggered = elapsed_minutes >= threshold_t

        if action_triggered and time_triggered:
            reason = CadenceTriggerReason.BOTH_BOUNDARIES
            triggered = True
        elif action_triggered:
            reason = CadenceTriggerReason.ACTION_BOUNDARY
            triggered = True
        elif time_triggered:
            reason = CadenceTriggerReason.TIME_BOUNDARY
            triggered = True
        else:
            reason = CadenceTriggerReason.NONE
            triggered = False

        return CadenceEvaluationResult(
            triggered=triggered,
            reason=reason,
            actions_executed=state.action_count,
            elapsed_minutes=round(elapsed_minutes, 4),
            threshold_actions=threshold_n,
            threshold_minutes=threshold_t,
            tenant_id=tenant_id,
            session_id=session_id,
            evaluated_at=now.isoformat()
        )

    def record_action_and_evaluate(
        self,
        task_id: int,
        user_id: int,
        mode: str,
        action_name: str,
        action_payload: Optional[Dict[str, Any]] = None,
        db_session: Optional[Session] = None,
        session_id: Optional[str] = None,
        current_time: Optional[datetime] = None,
        max_actions: Optional[int] = None,
        max_minutes: Optional[float] = None
    ) -> Optional[CadenceEvaluationResult]:
        """
        Records an executed action for an AUTONOMOUS task, increments batch counters,
        and if the periodic threshold (N actions or T minutes) is reached, emits a
        canonical CHITRA periodic oversight checkpoint event.

        Scope: Strictly applies to AUTONOMOUS mode tasks. REACTIVE / DELIBERATIVE / FEDERATED
        tasks are ignored per Whitesheet §12.5.
        """
        # Whitesheet §12.5: Periodic cadence applies specifically to low-risk autonomous operations
        if str(mode).upper() != "AUTONOMOUS":
            return None

        tenant_id = f"tenant_{user_id}"
        state = self._get_or_create_state(tenant_id=tenant_id, session_id=session_id)
        now = current_time or datetime.now(timezone.utc)

        # 1. Record action into active interval batch
        state.action_count += 1
        state.recent_actions.append({
            "task_id": task_id,
            "action": action_name,
            "recorded_at": now.isoformat(),
            "payload_summary": str(action_payload)[:200] if action_payload else None
        })

        # 2. Evaluate cadence thresholds
        eval_result = self.evaluate_cadence(
            tenant_id=tenant_id,
            session_id=session_id,
            current_time=now,
            max_actions=max_actions,
            max_minutes=max_minutes
        )

        # 3. If triggered, emit canonical CHITRA Periodic Oversight Checkpoint
        if eval_result.triggered and db_session is not None:
            self._emit_periodic_checkpoint(
                db=db_session,
                task_id=task_id,
                user_id=user_id,
                tenant_id=tenant_id,
                session_id=session_id,
                eval_result=eval_result,
                batch_actions=list(state.recent_actions)
            )
            # Reset counters for next interval
            state.reset_interval(current_time=now)

        return eval_result

    def _emit_periodic_checkpoint(
        self,
        db: Session,
        task_id: int,
        user_id: int,
        tenant_id: str,
        session_id: Optional[str],
        eval_result: CadenceEvaluationResult,
        batch_actions: List[Dict[str, Any]]
    ):
        """
        Appends the periodic oversight checkpoint event into the CHITRA cryptographic hash chain.
        Conforms to Whitesheet §12.5 (Periodic Oversight Tier) & §8.3 (Audit Ledger).
        """
        try:
            chitra_repository.append_event(
                db=db,
                task_id=task_id,
                faculty="MARYADA",
                event_type="periodic_oversight_checkpoint",
                decision={
                    "cadence": "PERIODIC",
                    "trigger_reason": eval_result.reason.value,
                    "batch_size": eval_result.actions_executed,
                    "elapsed_minutes": eval_result.elapsed_minutes,
                    "threshold_actions": eval_result.threshold_actions,
                    "threshold_minutes": eval_result.threshold_minutes,
                    "batch_actions": batch_actions,
                    "tenant_id": tenant_id,
                    "justification": (
                        f"Periodic oversight checkpoint triggered per CP-203 "
                        f"({eval_result.actions_executed} actions / {eval_result.elapsed_minutes:.2f} mins elapsed)."
                    )
                },
                session_id=session_id or f"ses_cadence_{task_id}",
                confidence=1.0,
                outcome={
                    "status": "CHECKPOINT_RECORDED",
                    "cadence": "PERIODIC",
                    "non_blocking_review": True
                },
                user_id=user_id
            )
            logger.info(
                f"Periodic oversight checkpoint recorded in CHITRA for task {task_id} "
                f"({eval_result.reason.value}: {eval_result.actions_executed} actions)"
            )
        except Exception as e:
            logger.error(f"Failed to append periodic oversight checkpoint in CHITRA: {e}", exc_info=True)


# Global singleton instance (production default: N=50 actions, T=30.0 minutes)
oversight_cadence_tracker = PeriodicOversightCadenceTracker()
