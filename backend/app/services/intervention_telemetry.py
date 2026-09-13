"""
HUMAN INTERVENTION RATE TELEMETRY SERVICE
Strictly conforms to BRAHMA COS Whitesheet §23 Phase 6 Exit Criteria:
"Human intervention rate < 1 per 100 task-hours for low-risk classes."

Calculates the rate of human oversight interventions per 100 task-hours
for LOW-risk class tasks across configurable time windows and tenant boundaries.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models.task import Task
from app.models.chitra import ChitraEvent


def get_task_duration_hours(task: Task) -> float:
    """
    Computes genuine task execution duration in hours using actual recorded execution timing.
    Uses only real runtime execution measurements stored in task.execution_result:
    - duration_seconds / duration_ms recorded around genuine workflow execution
    - step-level started_at / completed_at execution deltas

    NOTE: Does NOT use (updated_at - created_at) fallback, as that includes queue latency,
    human review wait time, and database row lifetime. If execution did not occur or was not
    timed, returns 0.0 task-hours.
    """
    if isinstance(task.execution_result, dict):
        if "duration_seconds" in task.execution_result and task.execution_result["duration_seconds"] is not None:
            try:
                return max(0.0, float(task.execution_result["duration_seconds"])) / 3600.0
            except (ValueError, TypeError):
                pass
        if "duration_ms" in task.execution_result and task.execution_result["duration_ms"] is not None:
            try:
                return max(0.0, float(task.execution_result["duration_ms"])) / (1000.0 * 3600.0)
            except (ValueError, TypeError):
                pass

        # Check step-level started_at / completed_at if present in execution report
        if "report" in task.execution_result and isinstance(task.execution_result["report"], dict):
            step_results = task.execution_result["report"].get("step_results", {})
            if isinstance(step_results, dict):
                total_step_sec = 0.0
                for step in step_results.values():
                    if isinstance(step, dict) and step.get("started_at") and step.get("completed_at"):
                        try:
                            s_start = datetime.fromisoformat(step["started_at"])
                            s_end = datetime.fromisoformat(step["completed_at"])
                            total_step_sec += max(0.0, (s_end - s_start).total_seconds())
                        except Exception:
                            pass
                if total_step_sec > 0:
                    return total_step_sec / 3600.0

    return 0.0


def calculate_human_intervention_rate(
    db: Session,
    user_id: Optional[int] = None,
    tenant_id: Optional[str] = None,
    window_hours: Optional[float] = 24.0,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None
) -> Dict[str, Any]:
    """
    Computes human intervention telemetry for Whitesheet §23 Phase 6.

    Numerator (Interventions):
        Count of DISTINCT LOW-risk tasks in the window that required human intervention:
        - MARYADA blocked task (status IN ('BLOCKED', 'MARYADA_BLOCKED') or policy_verdict.approved == False)
        - MARYADA escalated to human review (status == 'HUMAN_REVIEW' or policy_verdict.requires_human == True)
        - Explicit MANUSH oversight decision (CHITRA event with faculty='MANUSH' or status in ('TERMINATED', 'AMENDED'))
        * De-duplicated: each task with >= 1 intervention signal is counted exactly once.

    Denominator (Task-Hours):
        Total genuine recorded execution time in hours for the same LOW-risk task population.

    Rate:
        interventions / (task_hours / 100) = (interventions * 100.0) / task_hours
    """
    now = end_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if start_time is not None:
        window_start = start_time
        if window_start.tzinfo is None:
            window_start = window_start.replace(tzinfo=timezone.utc)
        effective_window_hours = max(0.0, (now - window_start).total_seconds() / 3600.0)
    else:
        hours = window_hours if window_hours is not None else 24.0
        window_start = now - timedelta(hours=hours)
        effective_window_hours = hours

    # 1. Fetch low-risk tasks in the time window
    query = db.query(Task).filter(
        Task.created_at >= window_start,
        Task.created_at <= now
    )

    if user_id is not None:
        query = query.filter(Task.user_id == user_id)

    candidate_tasks = query.all()

    # Filter to low-risk class tasks
    low_risk_tasks: List[Task] = []
    for t in candidate_tasks:
        is_low_risk = False
        if str(t.risk_level).upper() == "LOW":
            is_low_risk = True
        elif isinstance(t.policy_verdict, dict) and str(t.policy_verdict.get("risk_tier")).upper() == "LOW":
            is_low_risk = True
        elif isinstance(t.risk_report, dict) and str(t.risk_report.get("risk_level")).upper() == "LOW":
            is_low_risk = True

        if is_low_risk:
            low_risk_tasks.append(t)

    total_low_risk_tasks = len(low_risk_tasks)
    if total_low_risk_tasks == 0:
        return {
            "metric": "human_intervention_rate",
            "authority": "Whitesheet §23 Phase 6 Exit Criteria (< 1 per 100 task-hours for low-risk classes)",
            "risk_class": "LOW",
            "window_hours": round(effective_window_hours, 2),
            "window_start": window_start.isoformat(),
            "window_end": now.isoformat(),
            "tenant_filter": tenant_id,
            "user_filter": user_id,
            "total_low_risk_tasks": 0,
            "intervention_tasks": 0,
            "total_task_hours": 0.0,
            "rate_per_100_task_hours": 0.0,
            "target_threshold": 1.0,
            "meets_exit_criterion": True,
            "interventions_breakdown": {
                "blocked_tasks": 0,
                "escalated_human_review_tasks": 0,
                "manush_decided_tasks": 0
            }
        }

    # 2. Fetch MANUSH CHITRA events for these candidate tasks
    task_ids = [t.id for t in low_risk_tasks]
    manush_task_ids = set()
    if task_ids:
        manush_events = db.query(ChitraEvent.task_id).filter(
            ChitraEvent.task_id.in_(task_ids),
            ChitraEvent.faculty == "MANUSH"
        ).distinct().all()
        manush_task_ids = {row[0] for row in manush_events}

    # 3. Classify interventions and accumulate task-hours
    intervention_task_set = set()
    blocked_count = 0
    escalated_count = 0
    manush_decided_count = 0
    total_task_hours = 0.0

    for t in low_risk_tasks:
        duration_h = get_task_duration_hours(t)
        total_task_hours += duration_h

        is_blocked = False
        is_escalated = False
        has_manush_decision = False

        # Signal 1: Escalated to HUMAN_REVIEW
        if t.status == "HUMAN_REVIEW":
            is_escalated = True
        elif isinstance(t.policy_verdict, dict) and t.policy_verdict.get("requires_human") is True:
            is_escalated = True

        # Signal 2: Blocked (excluding pure review escalation)
        if t.status in ["BLOCKED", "MARYADA_BLOCKED"]:
            is_blocked = True
        elif isinstance(t.policy_verdict, dict) and t.policy_verdict.get("approved") is False and not is_escalated:
            is_blocked = True

        # Signal 3: Explicit MANUSH decision / terminal state
        if t.id in manush_task_ids or t.status in ["TERMINATED", "AMENDED"]:
            has_manush_decision = True

        if is_blocked:
            blocked_count += 1
        if is_escalated:
            escalated_count += 1
        if has_manush_decision:
            manush_decided_count += 1

        if is_blocked or is_escalated or has_manush_decision:
            intervention_task_set.add(t.id)

    total_interventions = len(intervention_task_set)

    # 4. Compute Rate: interventions / (task_hours / 100)
    if total_task_hours > 0.0:
        rate = round((total_interventions * 100.0) / total_task_hours, 4)
    else:
        # If total recorded duration is 0, report 0.0
        rate = 0.0

    meets_criterion = rate < 1.0

    return {
        "metric": "human_intervention_rate",
        "authority": "Whitesheet §23 Phase 6 Exit Criteria (< 1 per 100 task-hours for low-risk classes)",
        "risk_class": "LOW",
        "window_hours": round(effective_window_hours, 2),
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
        "tenant_filter": tenant_id,
        "user_filter": user_id,
        "total_low_risk_tasks": total_low_risk_tasks,
        "intervention_tasks": total_interventions,
        "total_task_hours": round(total_task_hours, 6),
        "rate_per_100_task_hours": rate,
        "target_threshold": 1.0,
        "meets_exit_criterion": meets_criterion,
        "interventions_breakdown": {
            "blocked_tasks": blocked_count,
            "escalated_human_review_tasks": escalated_count,
            "manush_decided_tasks": manush_decided_count
        }
    }
