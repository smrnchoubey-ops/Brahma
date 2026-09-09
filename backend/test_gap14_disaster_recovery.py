"""
GAP #14 TEST SUITE: Disaster Recovery Drill for BRAHMA COS
Strictly conforms to Whitesheet §14 (Failure Taxonomy, Idempotency, Recovery),
Appendix H (FH-4), Appendix I (RB-1 Cold Start, RB-2 Failure Recovery),
and Phase 6 Exit Criterion: "Full disaster-recovery drill passed."
"""
import pytest
import uuid
from fastapi.testclient import TestClient

from main import app
from app.db.database import SessionLocal
from app.models.user import User
from app.models.task import Task
from app.models.chitra import ChitraEvent
from app.core.security import get_password_hash
from app.repositories.chitra_repository import chitra_repository
from app.services.chitra_verifier import chitra_verifier
from app.core.disaster_recovery import DisasterRecoveryEngine, DisasterRecoveryReport


@pytest.fixture(scope="module")
def setup_users():
    with SessionLocal() as db:
        user_a = db.query(User).filter(User.username == "user_dr_tenant_a").first()
        if not user_a:
            user_a = User(username="user_dr_tenant_a", hashed_password=get_password_hash("passA"))
            db.add(user_a)

        user_b = db.query(User).filter(User.username == "user_dr_tenant_b").first()
        if not user_b:
            user_b = User(username="user_dr_tenant_b", hashed_password=get_password_hash("passB"))
            db.add(user_b)

        db.commit()
        db.refresh(user_a)
        db.refresh(user_b)
        return user_a.id, user_b.id


def test_dr_reconciles_unexecuted_task(setup_users):
    user_a_id, _ = setup_users
    with SessionLocal() as db:
        # Simulate in-flight task interrupted by sudden service crash before execution
        task = Task(
            user_id=user_a_id,
            title="DR Test Pre-Execution Task",
            prompt="Simulate unexecuted task during power loss",
            status="RUNNING",
            mode="AUTONOMOUS",
            risk_level="LOW"
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        # Initial CHITRA start event
        chitra_repository.append_event(
            db=db,
            task_id=task.id,
            faculty="BUDDHI",
            event_type="intent",
            decision={"parsed_intent": "dr_test"},
            session_id=f"ses_dr_{task.id}",
            confidence=0.95,
            outcome={"status": "IN_PROGRESS"},
            user_id=user_a_id
        )

        # Run DR Drill
        report: DisasterRecoveryReport = DisasterRecoveryEngine.execute_recovery_drill(db, user_id=user_a_id)

        assert report.status == "SUCCESS"
        assert task.id in report.reconciled_task_ids
        
        # Verify task is safely transitioned to RECOVERED with audit trail
        db.refresh(task)
        assert task.status == "RECOVERED"
        assert task.execution_result["status"] == "RECOVERED_AFTER_CRASH"
        assert task.execution_result["idempotency_protected"] is True

        # Verify CHITRA DR event was recorded
        dr_events = db.query(ChitraEvent).filter(
            ChitraEvent.task_id == task.id,
            ChitraEvent.faculty == "SYSTEM",
            ChitraEvent.event_type == "escalation"
        ).all()
        assert len(dr_events) >= 1
        assert dr_events[-1].decision["runtime_status"] == "DISASTER_RECOVERY_RECONCILED"
        assert dr_events[-1].decision["recovery_action"] == "RECONCILED_INTERRUPTED_SAFE_STATE"


def test_dr_reconciles_already_executed_task_without_duplicate(setup_users):
    user_a_id, _ = setup_users
    with SessionLocal() as db:
        # Simulate task where tool executed, but process died right before status became COMPLETED
        task = Task(
            user_id=user_a_id,
            title="DR Test Post-Execution Task",
            prompt="Simulate crash after tool execution",
            status="RUNNING",
            mode="AUTONOMOUS",
            risk_level="LOW"
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        # Append RACHIT EXECUTED event
        chitra_repository.append_event(
            db=db,
            task_id=task.id,
            faculty="RACHIT",
            event_type="action",
            decision={"tool": "safe_calc", "runtime_status": "EXECUTED"},
            session_id=f"ses_dr_{task.id}",
            confidence=1.0,
            outcome={"status": "SUCCESS", "output": "result_value_123"},
            user_id=user_a_id
        )

        # Run DR Drill
        report: DisasterRecoveryReport = DisasterRecoveryEngine.execute_recovery_drill(db, user_id=user_a_id)

        assert report.status == "SUCCESS"
        assert report.duplicate_executions_prevented >= 1
        assert task.id in report.reconciled_task_ids

        # Verify status is COMPLETED and NO duplicate execution happened
        db.refresh(task)
        assert task.status == "COMPLETED"

        # Verify CHITRA DR event was recorded
        dr_events = db.query(ChitraEvent).filter(
            ChitraEvent.task_id == task.id,
            ChitraEvent.faculty == "SYSTEM"
        ).all()
        assert len(dr_events) >= 1
        assert dr_events[-1].decision["recovery_action"] == "RECONCILED_COMPLETED_NO_DUPLICATE"


def test_dr_preserves_chitra_hash_chain_integrity(setup_users):
    user_a_id, _ = setup_users
    with SessionLocal() as db:
        task = Task(
            user_id=user_a_id,
            title="DR Hash Chain Verification Task",
            prompt="Verify cryptographic audit chain after DR",
            status="RUNNING",
            mode="AUTONOMOUS",
            risk_level="LOW"
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        # Multiple events in sequence
        for fac in ["BUDDHI", "MANAS", "MARYADA"]:
            chitra_repository.append_event(
                db=db,
                task_id=task.id,
                faculty=fac,
                event_type="evaluation",
                decision={"approved": True},
                session_id=f"ses_dr_chain_{task.id}",
                confidence=0.99,
                outcome={"ok": True},
                user_id=user_a_id
            )

        # Execute DR
        report = DisasterRecoveryEngine.execute_recovery_drill(db, user_id=user_a_id)
        assert report.status == "SUCCESS"
        assert report.broken_chains_detected == 0

        # Run full cryptographic verifier
        v_result = chitra_verifier.verify_task_chain(db, task.id, user_id=user_a_id)
        assert v_result.valid is True
        assert v_result.events_checked >= 4  # 3 prior + 1 DR event
        assert v_result.chain_status == "VERIFIED"
        assert v_result.signature_status == "VALID"


def test_dr_enforces_tenant_isolation(setup_users):
    user_a_id, user_b_id = setup_users
    with SessionLocal() as db:
        # Create orphaned RUNNING task for Tenant A
        task_a = Task(
            user_id=user_a_id,
            title="Tenant A Task",
            prompt="Tenant A task before crash",
            status="RUNNING",
            mode="AUTONOMOUS"
        )
        # Create orphaned RUNNING task for Tenant B
        task_b = Task(
            user_id=user_b_id,
            title="Tenant B Task",
            prompt="Tenant B task before crash",
            status="RUNNING",
            mode="AUTONOMOUS"
        )
        db.add_all([task_a, task_b])
        db.commit()
        db.refresh(task_a)
        db.refresh(task_b)

        # Run DR specifically for Tenant A (using tenant_id string format)
        report_a = DisasterRecoveryEngine.execute_recovery_drill(db, tenant_id=f"tenant_{user_a_id}")
        
        db.refresh(task_a)
        db.refresh(task_b)

        # Tenant A task must be reconciled
        assert task_a.id in report_a.reconciled_task_ids
        assert task_a.status == "RECOVERED"

        # Tenant B task must NOT be touched by Tenant A's recovery scope
        assert task_b.id not in report_a.reconciled_task_ids
        assert task_b.status == "RUNNING"

        # Now run DR for Tenant B
        report_b = DisasterRecoveryEngine.execute_recovery_drill(db, tenant_id=f"tenant_{user_b_id}")
        db.refresh(task_b)
        assert task_b.id in report_b.reconciled_task_ids
        assert task_b.status == "RECOVERED"


def test_automatic_startup_hook_reconciles_interrupted_tasks(setup_users):
    """
    Tests that FastAPI app startup automatically triggers Disaster Recovery reconciliation.
    """
    user_a_id, _ = setup_users
    with SessionLocal() as db:
        task = Task(
            user_id=user_a_id,
            title="Startup Hook Recovery Task",
            prompt="Interrupted before cold start",
            status="RUNNING",
            mode="AUTONOMOUS"
        )
        db.add(task)
        db.commit()
        db.refresh(task)

    # Initialize TestClient to trigger FastAPI startup event handlers
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200

    # Task should now be automatically reconciled on startup
    with SessionLocal() as db:
        reconciled_task = db.query(Task).filter(Task.id == task.id).first()
        assert reconciled_task.status in ["RECOVERED", "COMPLETED"]
