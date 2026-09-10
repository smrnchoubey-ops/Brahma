"""
GAP #12 TEST SUITE: Periodic Human Oversight Cadence Tracker
Strictly validates:
- Whitesheet §12.5 (Cadence Tiers & Periodic Oversight)
- Whitesheet Appendix A / CP-203 (Default N=50 actions OR T=30 minutes)
- Configurable threshold support (environment variable / constructor override)
- Action boundary trigger & Time elapsed boundary trigger
- Non-blocking batch review checkpoint semantics
- Canonical CHITRA event generation (faculty="MARYADA", event_type="periodic_oversight_checkpoint")
- Strict scoping to AUTONOMOUS mode operations (REACTIVE/DELIBERATIVE/FEDERATED ignored)
"""
import pytest
import os
import uuid
from datetime import datetime, timezone, timedelta

from app.db.database import SessionLocal, engine
from app.models.user import User
from app.models.task import Task
from app.models.chitra import ChitraEvent
from app.core.security import get_password_hash
from app.core.manush.cadence import (
    PeriodicOversightCadenceTracker,
    CadenceTriggerReason,
    CadenceEvaluationResult
)
from app.services.chitra_verifier import chitra_verifier


@pytest.fixture(scope="module")
def setup_users():
    # Pre-flight check: PostgreSQL dialect
    assert engine.dialect.name == "postgresql", f"Test requires PostgreSQL, got {engine.dialect.name}"

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "user_gap12_cadence_unit").first()
        if not user:
            user = User(username="user_gap12_cadence_unit", hashed_password=get_password_hash("pass123"))
            db.add(user)
            db.commit()
            db.refresh(user)

        user_id = user.id
        db.query(Task).filter(Task.user_id == user_id).delete(synchronize_session=False)
        db.commit()

        return user_id


def test_1_canonical_cp203_production_defaults():
    """Validates production defaults conform to Whitesheet CP-203 (N=50, T=30.0 min)."""
    tracker = PeriodicOversightCadenceTracker()
    assert tracker.DEFAULT_MAX_ACTIONS == 50
    assert tracker.DEFAULT_MAX_MINUTES == 30.0
    assert tracker.max_actions == 50
    assert tracker.max_minutes == 30.0


def test_2_configurable_threshold_overrides():
    """Validates configurable thresholds via constructor parameters and environment variables."""
    # Constructor override
    custom_tracker = PeriodicOversightCadenceTracker(default_max_actions=5, default_max_minutes=2.5)
    assert custom_tracker.max_actions == 5
    assert custom_tracker.max_minutes == 2.5

    # Environment variable override
    os.environ["OVERSIGHT_CADENCE_MAX_ACTIONS"] = "10"
    os.environ["OVERSIGHT_CADENCE_MAX_MINUTES"] = "15.0"
    try:
        env_tracker = PeriodicOversightCadenceTracker()
        assert env_tracker.max_actions == 10
        assert env_tracker.max_minutes == 15.0
    finally:
        os.environ.pop("OVERSIGHT_CADENCE_MAX_ACTIONS", None)
        os.environ.pop("OVERSIGHT_CADENCE_MAX_MINUTES", None)


def test_3_action_boundary_trigger():
    """Evaluates triggering at N actions boundary."""
    tracker = PeriodicOversightCadenceTracker(default_max_actions=3, default_max_minutes=60.0)
    tenant_id = "tenant_test_action"

    # Action 1
    eval1 = tracker.evaluate_cadence(tenant_id=tenant_id)
    assert eval1.triggered is False
    assert eval1.reason == CadenceTriggerReason.NONE

    # Simulate 2 actions
    state = tracker._get_or_create_state(tenant_id=tenant_id)
    state.action_count = 2
    eval2 = tracker.evaluate_cadence(tenant_id=tenant_id)
    assert eval2.triggered is False

    # Action 3 (Boundary reached)
    state.action_count = 3
    eval3 = tracker.evaluate_cadence(tenant_id=tenant_id)
    assert eval3.triggered is True
    assert eval3.reason == CadenceTriggerReason.ACTION_BOUNDARY
    assert eval3.actions_executed == 3


def test_4_time_boundary_trigger():
    """Evaluates triggering when T minutes have elapsed."""
    tracker = PeriodicOversightCadenceTracker(default_max_actions=100, default_max_minutes=10.0)
    tenant_id = "tenant_test_time"

    now = datetime.now(timezone.utc)
    past_time = now - timedelta(minutes=15)

    state = tracker._get_or_create_state(tenant_id=tenant_id)
    state.interval_start = past_time
    state.action_count = 5  # Below N=100

    eval_res = tracker.evaluate_cadence(tenant_id=tenant_id, current_time=now)
    assert eval_res.triggered is True
    assert eval_res.reason == CadenceTriggerReason.TIME_BOUNDARY
    assert eval_res.elapsed_minutes >= 10.0


def test_5_scope_restriction_ignores_non_autonomous(setup_users):
    """Periodic cadence strictly applies to AUTONOMOUS mode. REACTIVE/DELIBERATIVE are ignored."""
    user_id = setup_users
    tracker = PeriodicOversightCadenceTracker(default_max_actions=2, default_max_minutes=30.0)

    with SessionLocal() as db:
        # Submit REACTIVE actions
        res_reactive = tracker.record_action_and_evaluate(
            task_id=999,
            user_id=user_id,
            mode="REACTIVE",
            action_name="test_calc",
            db_session=db
        )
        assert res_reactive is None

        # Submit DELIBERATIVE actions
        res_deliberative = tracker.record_action_and_evaluate(
            task_id=999,
            user_id=user_id,
            mode="DELIBERATIVE",
            action_name="test_plan",
            db_session=db
        )
        assert res_deliberative is None

        # Confirm zero actions registered in tracker
        state = tracker._get_or_create_state(tenant_id=f"tenant_{user_id}")
        assert state.action_count == 0


def test_6_periodic_checkpoint_chitra_logging_and_reset(setup_users):
    """Autonomous actions trigger periodic CHITRA checkpoint and reset interval cleanly."""
    user_id = setup_users
    tracker = PeriodicOversightCadenceTracker(default_max_actions=2, default_max_minutes=30.0)
    tracker.reset_tracker()

    with SessionLocal() as db:
        task = Task(
            user_id=user_id,
            title="Periodic Cadence Task",
            prompt="Autonomous test prompt",
            status="RUNNING",
            mode="AUTONOMOUS",
            risk_level="LOW"
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        # Action 1 (Below threshold)
        res1 = tracker.record_action_and_evaluate(
            task_id=task.id,
            user_id=user_id,
            mode="AUTONOMOUS",
            action_name="action_1",
            action_payload={"tool": "calc", "arg": "1+1"},
            db_session=db
        )
        assert res1 is not None
        assert res1.triggered is False

        # Action 2 (Reaches threshold N=2 -> Checkpoint fired!)
        res2 = tracker.record_action_and_evaluate(
            task_id=task.id,
            user_id=user_id,
            mode="AUTONOMOUS",
            action_name="action_2",
            action_payload={"tool": "calc", "arg": "2+2"},
            db_session=db
        )
        assert res2 is not None
        assert res2.triggered is True
        assert res2.reason == CadenceTriggerReason.ACTION_BOUNDARY

        # Verify CHITRA Event in PostgreSQL
        chitra_evt = db.query(ChitraEvent).filter(
            ChitraEvent.task_id == task.id,
            ChitraEvent.event_type == "periodic_oversight_checkpoint"
        ).first()

        assert chitra_evt is not None
        assert chitra_evt.faculty == "MARYADA"
        assert chitra_evt.decision["cadence"] == "PERIODIC"
        assert chitra_evt.decision["batch_size"] == 2
        assert chitra_evt.decision["threshold_actions"] == 2
        assert len(chitra_evt.decision["batch_actions"]) == 2
        assert chitra_evt.outcome["non_blocking_review"] is True

        # Verify cryptographic hash chain
        verify_res = chitra_verifier.verify_task_chain(db, task.id)
        assert verify_res.valid is True

        # Verify tracker state reset
        state = tracker._get_or_create_state(tenant_id=f"tenant_{user_id}")
        assert state.action_count == 0
        assert state.total_checkpoints_triggered == 1
