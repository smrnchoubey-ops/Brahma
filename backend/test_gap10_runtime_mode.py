"""
GAP #10 TEST SUITE: Operational Mode Runtime Selector (Whitesheet §3.3 & Phase 6)
Validates explicit runtime mode selection, safety invariants, fail-safe validation,
CHITRA mode-selection auditing, and governance preservation.
"""
import pytest
import time
import uuid
from unittest.mock import patch
from fastapi.testclient import TestClient

from main import app
from app.db.database import SessionLocal
from app.models.user import User
from app.models.task import Task
from app.models.chitra import ChitraEvent
from app.core.runtime_mode import OperationalMode
from app.core.security import create_access_token, get_password_hash


def mock_brahma_invoke_safe(state):
    return {
        "status": "RACHIT_EXECUTED",
        "plan": {"summary": "Execute safe action", "tool": "calc"},
        "risk_report": {"risk_level": "LOW", "recommendation": "Proceed"},
        "policy_verdict": {"approved": True, "justification": "Safe deterministic execution"},
        "execution_result": {
            "status": "EXECUTED",
            "tool": "calc",
            "duration_ms": 50.0,
            "output": "42"
        }
    }


def mock_brahma_invoke_blocked(state):
    return {
        "status": "MARYADA_BLOCKED",
        "plan": {"summary": "Execute critical root action", "tool": "root_shell"},
        "risk_report": {"risk_level": "CRITICAL", "recommendation": "Block immediately"},
        "policy_verdict": {"approved": False, "requires_human": False, "justification": "Blocked: HIGH/CRITICAL risk."},
        "execution_result": None
    }


@pytest.fixture(scope="module")
def setup_users():
    with SessionLocal() as db:
        user_a = db.query(User).filter(User.username == "user_gap10_a").first()
        if not user_a:
            user_a = User(username="user_gap10_a", hashed_password=get_password_hash("pwdA"))
            db.add(user_a)
        
        user_b = db.query(User).filter(User.username == "user_gap10_b").first()
        if not user_b:
            user_b = User(username="user_gap10_b", hashed_password=get_password_hash("pwdB"))
            db.add(user_b)

        db.commit()
        db.refresh(user_a)
        db.refresh(user_b)
        
        u_a_id = user_a.id
        u_b_id = user_b.id

        # Clean prior tasks and audit events for isolated test run
        db.query(Task).filter(Task.user_id.in_([u_a_id, u_b_id])).delete(synchronize_session=False)
        db.commit()

    token_a = create_access_token(data={"sub": "user_gap10_a", "id": u_a_id})
    token_b = create_access_token(data={"sub": "user_gap10_b", "id": u_b_id})
    
    return {
        "u_a_id": u_a_id,
        "token_a": token_a,
        "headers_a": {"Authorization": f"Bearer {token_a}"},
        "u_b_id": u_b_id,
        "token_b": token_b,
        "headers_b": {"Authorization": f"Bearer {token_b}"}
    }


def test_1_operational_mode_enum_and_metadata():
    """Validates OperationalMode enum members and metadata per Whitesheet §3.3."""
    assert OperationalMode.validate_mode(None) == OperationalMode.REACTIVE
    assert OperationalMode.validate_mode("") == OperationalMode.REACTIVE
    assert OperationalMode.validate_mode("manual") == OperationalMode.REACTIVE
    assert OperationalMode.validate_mode("REACTIVE") == OperationalMode.REACTIVE
    assert OperationalMode.validate_mode("deliberative") == OperationalMode.DELIBERATIVE
    assert OperationalMode.validate_mode("AUTONOMOUS") == OperationalMode.AUTONOMOUS
    assert OperationalMode.validate_mode("federated") == OperationalMode.FEDERATED

    meta_auto = OperationalMode.get_mode_metadata(OperationalMode.AUTONOMOUS)
    assert meta_auto["is_autonomous"] is True
    assert meta_auto["retention_tier"] == "PERMANENT"

    meta_react = OperationalMode.get_mode_metadata(OperationalMode.REACTIVE)
    assert meta_react["is_autonomous"] is False


def test_2_invalid_mode_rejected_fail_safe(setup_users):
    """Submitting an invalid mode string fails safely with HTTP 400."""
    client = TestClient(app)
    resp = client.post(
        "/tasks/",
        json={"title": "Invalid Mode Task", "prompt": f"Test invalid mode {uuid.uuid4()}", "mode": "SUPER_ADMIN_BYPASS"},
        headers=setup_users["headers_a"]
    )
    assert resp.status_code == 400
    assert "Invalid operational mode" in resp.json()["detail"]


def test_3_normal_reactive_manual_mode_execution(setup_users):
    """Default/manual task submission operates in REACTIVE mode with zero regression."""
    client = TestClient(app)
    uid = uuid.uuid4().hex[:8]
    with patch("main.brahma_app.invoke", side_effect=mock_brahma_invoke_safe):
        resp = client.post(
            "/tasks/",
            json={"title": f"Manual Mode Task {uid}", "prompt": f"Normal single-turn query {uid}"},
            headers=setup_users["headers_a"]
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "REACTIVE"
        task_id = data["task_id"]

        time.sleep(0.3)

        with SessionLocal() as db:
            task = db.query(Task).filter(Task.id == task_id).first()
            assert task is not None
            assert task.mode == "REACTIVE"
            assert task.status == "COMPLETED"

            # Check CHITRA mode selection audit event
            chitra_evt = db.query(ChitraEvent).filter(ChitraEvent.task_id == task_id, ChitraEvent.faculty == "RUNTIME").first()
            assert chitra_evt is not None
            assert chitra_evt.decision["payload"]["mode"] == "REACTIVE"


def test_4_autonomous_mode_execution_and_chitra_audit(setup_users):
    """Explicit autonomous mode execution tags task as AUTONOMOUS and logs decision to CHITRA."""
    client = TestClient(app)
    uid = uuid.uuid4().hex[:8]
    with patch("main.brahma_app.invoke", side_effect=mock_brahma_invoke_safe):
        resp = client.post(
            "/tasks/",
            json={"title": f"Autonomous Pipeline Task {uid}", "prompt": f"Long-horizon execution task {uid}", "mode": "AUTONOMOUS"},
            headers=setup_users["headers_a"]
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "AUTONOMOUS"
        task_id = data["task_id"]

        time.sleep(0.3)

        with SessionLocal() as db:
            task = db.query(Task).filter(Task.id == task_id).first()
            assert task is not None
            assert task.mode == "AUTONOMOUS"
            assert task.status == "COMPLETED"

            # Check CHITRA mode selection audit event
            chitra_evt = db.query(ChitraEvent).filter(ChitraEvent.task_id == task_id, ChitraEvent.faculty == "RUNTIME").first()
            assert chitra_evt is not None
            assert chitra_evt.decision["payload"]["mode"] == "AUTONOMOUS"
            assert chitra_evt.decision["payload"]["is_autonomous"] is True
            assert chitra_evt.decision["payload"]["retention_tier"] == "PERMANENT"


def test_5_autonomous_mode_cannot_bypass_maryada_governance(setup_users):
    """Negative control: setting AUTONOMOUS mode cannot bypass MARYADA policy gate."""
    client = TestClient(app)
    uid = uuid.uuid4().hex[:8]
    with patch("main.brahma_app.invoke", side_effect=mock_brahma_invoke_blocked):
        resp = client.post(
            "/tasks/",
            json={"title": f"Malicious Autonomous Task {uid}", "prompt": f"Execute critical unauthorized command {uid}", "mode": "AUTONOMOUS"},
            headers=setup_users["headers_a"]
        )
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        time.sleep(0.3)

        with SessionLocal() as db:
            task = db.query(Task).filter(Task.id == task_id).first()
            assert task is not None
            assert task.mode == "AUTONOMOUS"
            assert task.status == "BLOCKED"
            assert task.policy_verdict["approved"] is False


def test_6_tenant_isolation_in_autonomous_mode(setup_users):
    """User B cannot view or access User A's autonomous tasks."""
    client = TestClient(app)
    uid = uuid.uuid4().hex[:8]
    with patch("main.brahma_app.invoke", side_effect=mock_brahma_invoke_safe):
        resp = client.post(
            "/tasks/",
            json={"title": f"User A Private Autonomous Task {uid}", "prompt": f"Tenant A proprietary work {uid}", "mode": "AUTONOMOUS"},
            headers=setup_users["headers_a"]
        )
        task_a_id = resp.json()["task_id"]

        # User B attempts to access User A's task -> 404 Not Found (Strict isolation)
        resp_b = client.get(f"/tasks/{task_a_id}", headers=setup_users["headers_b"])
        assert resp_b.status_code == 404
