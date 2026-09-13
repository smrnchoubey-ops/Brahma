"""
GAP #13 TEST SUITE: Human Intervention Rate Telemetry
Strictly validates:
- Whitesheet §23 Phase 6 Exit Criteria ("Human intervention rate < 1 per 100 task-hours for low-risk classes")
- LOW-risk task inclusion and non-low-risk task exclusion
- Intervention signal identification (MARYADA blocked, HUMAN_REVIEW, MANUSH decisions)
- De-duplication (multiple intervention signals on 1 task count as 1 intervention)
- Task duration accumulation in hours
- Rate calculation: interventions / (task_hours / 100)
- Multi-tenant / user isolation filtering
- Time-window filtering (e.g. 24h default vs custom window)
- Zero-task edge case (safe division-by-zero protection)
- Mounted API endpoint: GET /api/metrics/intervention-rate
"""
import pytest
import os
import uuid
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from main import app
from app.db.database import SessionLocal, engine
from app.models.user import User
from app.models.task import Task
from app.models.chitra import ChitraEvent
from app.core.security import get_password_hash, create_access_token
from app.services.intervention_telemetry import (
    calculate_human_intervention_rate,
    get_task_duration_hours
)


@pytest.fixture(scope="module")
def setup_users():
    # Pre-flight check: PostgreSQL dialect
    assert engine.dialect.name == "postgresql", f"Test requires PostgreSQL, got {engine.dialect.name}"

    with SessionLocal() as db:
        user_a = db.query(User).filter(User.username == "user_gap13_tenant_a").first()
        if not user_a:
            user_a = User(username="user_gap13_tenant_a", hashed_password=get_password_hash("pass123"))
            db.add(user_a)
            db.commit()
            db.refresh(user_a)

        user_b = db.query(User).filter(User.username == "user_gap13_tenant_b").first()
        if not user_b:
            user_b = User(username="user_gap13_tenant_b", hashed_password=get_password_hash("pass123"))
            db.add(user_b)
            db.commit()
            db.refresh(user_b)

        # Clear prior tasks
        db.query(Task).filter(Task.user_id.in_([user_a.id, user_b.id])).delete(synchronize_session=False)
        db.commit()

        return user_a.id, user_b.id


def test_1_low_risk_inclusion_and_high_risk_exclusion(setup_users):
    """Verifies LOW-risk tasks are included in telemetry and non-low-risk tasks are excluded."""
    user_a_id, _ = setup_users

    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        # 1. Low risk completed task
        t_low = Task(
            user_id=user_a_id,
            title="Low Risk Task",
            prompt="Simple math",
            status="COMPLETED",
            mode="AUTONOMOUS",
            risk_level="LOW",
            execution_result={"duration_seconds": 3600.0},  # 1 hour
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=1)
        )
        # 2. High risk task (should be excluded)
        t_high = Task(
            user_id=user_a_id,
            title="High Risk Task",
            prompt="Financial transfer",
            status="COMPLETED",
            mode="AUTONOMOUS",
            risk_level="HIGH",
            execution_result={"duration_seconds": 3600.0},
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=1)
        )
        db.add_all([t_low, t_high])
        db.commit()

        metrics = calculate_human_intervention_rate(db, user_id=user_a_id, window_hours=24.0, end_time=now)
        assert metrics["total_low_risk_tasks"] == 1
        assert metrics["intervention_tasks"] == 0
        assert metrics["total_task_hours"] == 1.0
        assert metrics["rate_per_100_task_hours"] == 0.0
        assert metrics["meets_exit_criterion"] is True


def test_2_intervention_counting_and_deduplication(setup_users):
    """Verifies that multiple intervention signals on a single task are de-duplicated."""
    user_a_id, _ = setup_users

    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        # Task with MULTIPLE intervention signals:
        # 1. status = HUMAN_REVIEW
        # 2. policy_verdict.requires_human = True
        # 3. policy_verdict.approved = False
        t_multi = Task(
            user_id=user_a_id,
            title="Multi Signal Intervention Task",
            prompt="Ambiguous operation",
            status="HUMAN_REVIEW",
            mode="AUTONOMOUS",
            risk_level="LOW",
            policy_verdict={"risk_tier": "LOW", "approved": False, "requires_human": True},
            execution_result={"duration_seconds": 1800.0},  # 0.5 hours
            created_at=now - timedelta(hours=1),
            updated_at=now
        )
        db.add(t_multi)
        db.commit()
        db.refresh(t_multi)

        # Also add a MANUSH chitra event for this task
        evt = ChitraEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            task_id=t_multi.id,
            session_id=f"ses_{t_multi.id}",
            timestamp=now,
            faculty="MANUSH",
            event_type="human_review",
            input_hash="hash_input",
            decision={"decision": "APPROVE"},
            confidence=1.0,
            outcome={"status": "APPROVED_BY_HUMAN"},
            constitutional_review="passed",
            prev_event_hash="hash_prev",
            this_event_hash=f"hash_{uuid.uuid4().hex}",
            signature="sig_test"
        )
        db.add(evt)
        db.commit()

        metrics = calculate_human_intervention_rate(db, user_id=user_a_id, window_hours=24.0, end_time=now)
        # Total low-risk tasks = 2 (t_low from test 1 + t_multi)
        assert metrics["total_low_risk_tasks"] == 2
        # Intervention tasks = 1 (only t_multi, counted exactly once)
        assert metrics["intervention_tasks"] == 1
        # Total task hours = 1.0 (from test 1) + 0.5 (from test 2) = 1.5 hours
        assert metrics["total_task_hours"] == 1.5
        # Rate = (1 / 1.5) * 100 = 66.6667
        assert abs(metrics["rate_per_100_task_hours"] - 66.6667) < 0.01
        assert metrics["meets_exit_criterion"] is False  # Rate > 1.0


def test_3_tenant_isolation_filtering(setup_users):
    """Verifies that user/tenant filtering strictly separates telemetry between tenants."""
    user_a_id, user_b_id = setup_users

    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        # Create a low-risk task for Tenant B with an intervention
        t_tenant_b = Task(
            user_id=user_b_id,
            title="Tenant B Task",
            prompt="Math for B",
            status="BLOCKED",
            mode="AUTONOMOUS",
            risk_level="LOW",
            execution_result={"duration_seconds": 3600.0},  # 1 hour
            created_at=now - timedelta(hours=1),
            updated_at=now
        )
        db.add(t_tenant_b)
        db.commit()

        metrics_b = calculate_human_intervention_rate(db, user_id=user_b_id, window_hours=24.0, end_time=now)
        assert metrics_b["total_low_risk_tasks"] == 1
        assert metrics_b["intervention_tasks"] == 1
        assert metrics_b["total_task_hours"] == 1.0
        assert metrics_b["rate_per_100_task_hours"] == 100.0

        # Tenant A's metrics must remain isolated (2 tasks, 1 intervention)
        metrics_a = calculate_human_intervention_rate(db, user_id=user_a_id, window_hours=24.0, end_time=now)
        assert metrics_a["total_low_risk_tasks"] == 2
        assert metrics_a["intervention_tasks"] == 1


def test_4_time_window_filtering(setup_users):
    """Verifies that tasks outside the requested window are excluded."""
    user_a_id, _ = setup_users

    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        # Task created 48 hours ago
        t_old = Task(
            user_id=user_a_id,
            title="Old Task",
            prompt="Old prompt",
            status="BLOCKED",
            mode="AUTONOMOUS",
            risk_level="LOW",
            execution_result={"duration_seconds": 3600.0},
            created_at=now - timedelta(hours=48),
            updated_at=now - timedelta(hours=47)
        )
        db.add(t_old)
        db.commit()

        # Query 12-hour window: only recent tasks included, t_old excluded
        metrics_12h = calculate_human_intervention_rate(db, user_id=user_a_id, window_hours=12.0, end_time=now)
        assert metrics_12h["window_hours"] == 12.0
        assert metrics_12h["total_low_risk_tasks"] == 2  # t_low (2h ago) and t_multi (1h ago)

        # Query 72-hour window: all 3 tasks included
        metrics_72h = calculate_human_intervention_rate(db, user_id=user_a_id, window_hours=72.0, end_time=now)
        assert metrics_72h["total_low_risk_tasks"] == 3


def test_5_zero_task_window_safe_division(setup_users):
    """Verifies that an empty window returns zero without division-by-zero errors."""
    user_a_id, _ = setup_users

    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        # Window in future -> 0 tasks
        future_start = now + timedelta(days=5)
        future_end = now + timedelta(days=6)

        metrics_empty = calculate_human_intervention_rate(
            db,
            user_id=user_a_id,
            start_time=future_start,
            end_time=future_end
        )
        assert metrics_empty["total_low_risk_tasks"] == 0
        assert metrics_empty["intervention_tasks"] == 0
        assert metrics_empty["total_task_hours"] == 0.0
        assert metrics_empty["rate_per_100_task_hours"] == 0.0
        assert metrics_empty["meets_exit_criterion"] is True


def test_6_api_endpoint_mounted_and_callable(setup_users):
    """Verifies GET /api/metrics/intervention-rate is mounted on FastAPI and callable."""
    user_a_id, _ = setup_users
    token = create_access_token(data={"sub": "user_gap13_tenant_a", "id": user_a_id})
    headers = {"Authorization": f"Bearer {token}"}

    client = TestClient(app)
    resp = client.get("/api/metrics/intervention-rate?window_hours=24", headers=headers)
    assert resp.status_code == 200, f"Endpoint call failed: {resp.text}"

    data = resp.json()
    assert data["metric"] == "human_intervention_rate"
    assert data["risk_class"] == "LOW"
    assert "rate_per_100_task_hours" in data
    assert "meets_exit_criterion" in data
    assert "interventions_breakdown" in data
    assert data["user_filter"] == user_a_id


def test_7_genuine_execution_duration_captured_in_runtime(setup_users):
    """Verifies genuine execution duration is measured and persisted in task.execution_result."""
    from main import run_agent_workflow
    user_a_id, _ = setup_users

    with SessionLocal() as db:
        task = Task(
            user_id=user_a_id,
            title="Timing Test Task",
            prompt="Simple greeting test",
            status="PENDING",
            mode="AUTONOMOUS",
            risk_level="LOW"
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id = task.id

        run_agent_workflow(task_id, task.prompt, mode="AUTONOMOUS", db_session=db)

        db.refresh(task)
        assert task.status in ["COMPLETED", "BLOCKED", "HUMAN_REVIEW"]
        if task.status == "COMPLETED":
            assert isinstance(task.execution_result, dict)
            assert "duration_seconds" in task.execution_result
            assert "duration_ms" in task.execution_result
            assert "execution_start" in task.execution_result
            assert "execution_end" in task.execution_result
            assert task.execution_result["duration_seconds"] >= 0.0
            dur_hours = get_task_duration_hours(task)
            assert dur_hours >= 0.0


def test_8_duration_measured_around_actual_execution_not_created_at_delta(setup_users):
    """Verifies duration uses ONLY genuine execution timing, NOT created_at/updated_at delta."""
    user_a_id, _ = setup_users

    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        # Task created 24 hours ago, updated now (delta = 24h), but actual execution was 3.6 seconds (0.001 hours)
        t = Task(
            user_id=user_a_id,
            title="Duration Delta Test",
            prompt="Test delta",
            status="COMPLETED",
            mode="AUTONOMOUS",
            risk_level="LOW",
            execution_result={"duration_seconds": 3.6, "duration_ms": 3600.0},
            created_at=now - timedelta(hours=24),
            updated_at=now
        )
        db.add(t)
        db.commit()

        dur_hours = get_task_duration_hours(t)
        # Must be 3.6 / 3600 = 0.001 hours, NOT 24.0 hours
        assert abs(dur_hours - 0.001) < 1e-6


def test_9_human_review_and_blocked_waiting_time_not_counted(setup_users):
    """Verifies waiting time for HUMAN_REVIEW and BLOCKED tasks without execution is NOT counted."""
    user_a_id, _ = setup_users

    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        # 1. Blocked task (no execution occurred)
        t_blocked = Task(
            user_id=user_a_id,
            title="Blocked Task No Exec",
            prompt="Blocked intent",
            status="BLOCKED",
            mode="AUTONOMOUS",
            risk_level="LOW",
            execution_result={"status": "BLOCKED", "reason": "MARYADA policy rejected"},
            created_at=now - timedelta(hours=5),
            updated_at=now
        )
        # 2. Human review task (waiting in queue for 10 hours)
        t_review = Task(
            user_id=user_a_id,
            title="Human Review Task Waiting",
            prompt="Requires human oversight",
            status="HUMAN_REVIEW",
            mode="AUTONOMOUS",
            risk_level="LOW",
            execution_result=None,
            created_at=now - timedelta(hours=10),
            updated_at=now
        )
        db.add_all([t_blocked, t_review])
        db.commit()

        assert get_task_duration_hours(t_blocked) == 0.0
        assert get_task_duration_hours(t_review) == 0.0


def test_10_security_user_a_cannot_query_user_b_telemetry(setup_users):
    """Verifies User A receives 403 Forbidden when attempting to query User B's user_id."""
    user_a_id, user_b_id = setup_users
    token_a = create_access_token(data={"sub": "user_gap13_tenant_a", "id": user_a_id})
    headers_a = {"Authorization": f"Bearer {token_a}"}

    client = TestClient(app)
    # User A tries to pass User B's ID in user_id query parameter
    resp = client.get(f"/api/metrics/intervention-rate?user_id={user_b_id}", headers=headers_a)
    assert resp.status_code == 403, f"Expected 403 Forbidden, got {resp.status_code}: {resp.text}"
    assert "Access denied" in resp.json()["detail"]


def test_11_security_user_a_cannot_query_user_b_tenant_telemetry(setup_users):
    """Verifies User A receives 403 Forbidden when attempting to query User B's tenant_id."""
    user_a_id, user_b_id = setup_users
    token_a = create_access_token(data={"sub": "user_gap13_tenant_a", "id": user_a_id})
    headers_a = {"Authorization": f"Bearer {token_a}"}

    client = TestClient(app)
    # User A tries to pass User B's tenant_id in tenant_id query parameter
    resp = client.get(f"/api/metrics/intervention-rate?tenant_id=tenant_{user_b_id}", headers=headers_a)
    assert resp.status_code == 403, f"Expected 403 Forbidden, got {resp.status_code}: {resp.text}"
    assert "Access denied" in resp.json()["detail"]


def test_12_own_user_telemetry_authorized(setup_users):
    """Verifies User A can query their own telemetry with explicit matching filters or defaults."""
    user_a_id, _ = setup_users
    token_a = create_access_token(data={"sub": "user_gap13_tenant_a", "id": user_a_id})
    headers_a = {"Authorization": f"Bearer {token_a}"}

    client = TestClient(app)
    # 1. Default query (no params)
    resp_default = client.get("/api/metrics/intervention-rate", headers=headers_a)
    assert resp_default.status_code == 200
    assert resp_default.json()["user_filter"] == user_a_id
    assert resp_default.json()["tenant_filter"] == f"tenant_{user_a_id}"

    # 2. Explicit matching own params
    resp_explicit = client.get(
        f"/api/metrics/intervention-rate?user_id={user_a_id}&tenant_id=tenant_{user_a_id}",
        headers=headers_a
    )
    assert resp_explicit.status_code == 200
    assert resp_explicit.json()["user_filter"] == user_a_id
    assert resp_explicit.json()["tenant_filter"] == f"tenant_{user_a_id}"

