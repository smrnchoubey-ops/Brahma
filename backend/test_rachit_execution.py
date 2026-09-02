import os
import sys
from dotenv import load_dotenv

# Ensure backend is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from agents.nodes.rachit import rachit_node
from agents.execution import execute_action, ACTION_REGISTRY
from agents.state import AgentState
from app.db.database import SessionLocal
from app.models.audit import Audit

def test_rachit_suite():
    print("=" * 60)
    print("RACHIT REAL EXECUTION ENGINE - TEST SUITE")
    print("=" * 60)
    
    passed_tests = 0
    total_tests = 0

    # Ensure test tasks exist in DB to satisfy foreign key constraint
    db = SessionLocal()
    from app.models.user import User
    from app.models.task import Task
    try:
        user = db.query(User).first()
        if not user:
            user = User(username="admin", hashed_password="pw")
            db.add(user)
            db.commit()
            db.refresh(user)
        
        test_tasks = []
        for i in range(5):
            t = Task(title=f"RACHIT Test Task {i+1}", prompt="Test Prompt", user_id=user.id)
            db.add(t)
            test_tasks.append(t)
        db.commit()
        for t in test_tasks:
            db.refresh(t)
        task_ids = [t.id for t in test_tasks]
    finally:
        db.close()

    # -------------------------------------------------------------
    # Test 1: Approved Safe Action -> Real Execution (Calculate)
    # -------------------------------------------------------------
    total_tests += 1
    print("\n[TEST 1] Approved Safe Action: Math Calculation (125 * 8)")
    state_math = {
        "task_id": task_ids[0],
        "trace_id": f"test-trace-{task_ids[0]}",
        "intent": "Calculate 125 * 8 for the quarterly projection",
        "knowledge_context": None,
        "current_agent": "MARYADA",
        "status": "MARYADA_APPROVED",
        "errors": [],
        "plan": {
            "summary": "Compute quarterly budget projection",
            "steps": ["Calculate arithmetic formula"],
            "tools_needed": ["calculate"],
            "assumptions": []
        },
        "risk_report": {"risk_level": "LOW", "failure_modes": [], "security_concerns": [], "recommendation": "Proceed"},
        "policy_verdict": {"risk_tier": "LOW", "approved": True, "requires_human": False, "justification": "Safe math"},
        "execution_result": None
    }
    res1 = rachit_node(state_math)
    assert res1["status"] == "RACHIT_EXECUTED", f"Expected RACHIT_EXECUTED, got {res1['status']}"
    calc_result = res1["execution_result"]["output"]["result"]
    assert calc_result == 1000, f"Expected 1000, got {calc_result}"
    print(f"Result: PASS -> Status: {res1['status']}, Action: {res1['execution_result']['action_name']}, Math Result: {calc_result}")
    passed_tests += 1

    # -------------------------------------------------------------
    # Test 2: Approved Safe Action -> Real Execution (Calendar Lookup)
    # -------------------------------------------------------------
    total_tests += 1
    print("\n[TEST 2] Approved Safe Action: Calendar Lookup for 2026")
    state_cal = {
        "task_id": task_ids[1],
        "trace_id": f"test-trace-{task_ids[1]}",
        "intent": "Look up holiday calendar for 2026",
        "knowledge_context": None,
        "current_agent": "MARYADA",
        "status": "MARYADA_APPROVED",
        "errors": [],
        "plan": {
            "summary": "Retrieve official holidays",
            "steps": ["Query corporate calendar"],
            "tools_needed": ["calendar_lookup"],
            "assumptions": []
        },
        "risk_report": {"risk_level": "LOW", "failure_modes": [], "security_concerns": [], "recommendation": "Proceed"},
        "policy_verdict": {"risk_tier": "LOW", "approved": True, "requires_human": False, "justification": "Safe calendar"},
        "execution_result": None
    }
    res2 = rachit_node(state_cal)
    assert res2["status"] == "RACHIT_EXECUTED"
    holidays = res2["execution_result"]["output"]["holidays"]
    assert len(holidays) > 0, "Expected non-empty holidays list"
    print(f"Result: PASS -> Status: {res2['status']}, Total Holidays Found: {len(holidays)}")
    passed_tests += 1

    # -------------------------------------------------------------
    # Test 3: Unapproved Action -> Aborted / BLOCKED
    # -------------------------------------------------------------
    total_tests += 1
    print("\n[TEST 3] Unapproved Action (policy_verdict.approved == False)")
    state_unapproved = {
        "task_id": task_ids[2],
        "trace_id": f"test-trace-{task_ids[2]}",
        "intent": "Transfer funds",
        "knowledge_context": None,
        "current_agent": "MARYADA",
        "status": "MARYADA_BLOCKED",
        "errors": [],
        "plan": {"summary": "High risk action", "steps": ["Initiate wire"], "tools_needed": [], "assumptions": []},
        "risk_report": {"risk_level": "HIGH", "failure_modes": ["Loss of funds"], "security_concerns": ["Unauthorized"], "recommendation": "Block"},
        "policy_verdict": {"risk_tier": "HIGH", "approved": False, "requires_human": False, "justification": "Blocked: High risk"},
        "execution_result": None
    }
    res3 = rachit_node(state_unapproved)
    assert res3["status"] == "RACHIT_BLOCKED", f"Expected RACHIT_BLOCKED, got {res3['status']}"
    assert res3["execution_result"]["status"] == "BLOCKED"
    print(f"Result: PASS -> Status: {res3['status']}, Reason: {res3['execution_result']['reason']}")
    passed_tests += 1

    # -------------------------------------------------------------
    # Test 4: Disallowed Dangerous Tool Request (Security Gate)
    # -------------------------------------------------------------
    total_tests += 1
    print("\n[TEST 4] Prohibited Tool Request (shell / subprocess)")
    state_dangerous = {
        "task_id": task_ids[3],
        "trace_id": f"test-trace-{task_ids[3]}",
        "intent": "Run shell command to clear logs",
        "knowledge_context": None,
        "current_agent": "MARYADA",
        "status": "MARYADA_APPROVED",
        "errors": [],
        "plan": {
            "summary": "Execute shell script",
            "steps": ["Run command"],
            "tools_needed": ["bash_shell", "subprocess"],
            "assumptions": []
        },
        "risk_report": {"risk_level": "LOW", "failure_modes": [], "security_concerns": [], "recommendation": "Proceed"},
        "policy_verdict": {"risk_tier": "LOW", "approved": True, "requires_human": False, "justification": "Testing security gate"},
        "execution_result": None
    }
    res4 = rachit_node(state_dangerous)
    assert res4["status"] == "RACHIT_BLOCKED", f"Expected RACHIT_BLOCKED, got {res4['status']}"
    assert "violates security policy" in res4["execution_result"]["error"]
    print(f"Result: PASS -> Status: {res4['status']}, Security Error: {res4['execution_result']['error']}")
    passed_tests += 1

    # -------------------------------------------------------------
    # Test 5: Execution Failure Handling (Division by Zero)
    # -------------------------------------------------------------
    total_tests += 1
    print("\n[TEST 5] Execution Failure Handling (Division by Zero in calculate)")
    state_div_zero = {
        "task_id": task_ids[4],
        "trace_id": f"test-trace-{task_ids[4]}",
        "intent": "Calculate 500 / 0",
        "knowledge_context": None,
        "current_agent": "MARYADA",
        "status": "MARYADA_APPROVED",
        "errors": [],
        "plan": {
            "summary": "Divide by zero",
            "steps": ["Compute value"],
            "tools_needed": ["calculate"],
            "assumptions": []
        },
        "risk_report": {"risk_level": "LOW", "failure_modes": [], "security_concerns": [], "recommendation": "Proceed"},
        "policy_verdict": {"risk_tier": "LOW", "approved": True, "requires_human": False, "justification": "Testing error handling"},
        "execution_result": None
    }
    res5 = rachit_node(state_div_zero)
    assert res5["status"] == "RACHIT_FAILED", f"Expected RACHIT_FAILED, got {res5['status']}"
    assert len(res5["errors"]) > 0, "Expected errors list to be populated"
    print(f"Result: PASS -> Status: {res5['status']}, Safe Error: {res5['execution_result']['error']}")
    passed_tests += 1

    # -------------------------------------------------------------
    # Test 6: Audit Logging Verification
    # -------------------------------------------------------------
    total_tests += 1
    print("\n[TEST 6] Audit Logging Verification in PostgreSQL")
    db = SessionLocal()
    try:
        audit_records = db.query(Audit).filter(Audit.task_id.in_(task_ids)).all()
        rachit_audits = [a for a in audit_records if a.agent == "RACHIT"]
        assert len(rachit_audits) >= 5, f"Expected at least 5 RACHIT audit records, found {len(rachit_audits)}"
        
        statuses_logged = {a.status for a in rachit_audits}
        assert "EXECUTED" in statuses_logged, "Expected EXECUTED status in audit logs"
        assert "BLOCKED" in statuses_logged, "Expected BLOCKED status in audit logs"
        assert "FAILED" in statuses_logged, "Expected FAILED status in audit logs"
        print(f"Result: PASS -> {len(rachit_audits)} audit records verified with statuses: {statuses_logged}")
        passed_tests += 1
    finally:
        db.close()

    print("\n" + "=" * 60)
    print(f"SUMMARY: {passed_tests} / {total_tests} TESTS PASSED (100%)")
    print("=" * 60)

if __name__ == "__main__":
    test_rachit_suite()
