import json
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database import SessionLocal, engine
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.core.manush.decision import ReviewStatus, ReviewDecisionType, HumanReviewDecision
from app.core.manush.service import manush_service, ManushOversightService
from app.core.tenant import TenantContext, get_current_tenant
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
from app.core.maryada.token import AuthorityToken
from app.core.maryada.verdict import AuthorityTier
from main import app

def run_persistence_forensics():
    db = SessionLocal()
    print("=================================================================")
    print("=== LIVE FORENSIC EVIDENCE: POSTGRESQL TASK PERSISTENCE SYNC ===")
    print("=================================================================\n")
    
    try:
        # -------------------------------------------------------------
        # Part 1: DELEGATE Live Execution & PostgreSQL Task Persistence
        # -------------------------------------------------------------
        user_del = db.query(User).filter(User.username == "delegate_persist_user").first()
        if not user_del:
            user_del = User(username="delegate_persist_user", hashed_password="hashed_pw_del_111", is_active=True)
            db.add(user_del)
            db.commit()
            db.refresh(user_del)

        tenant_del = f"tenant_{user_del.id}"
        
        plan_del = {
            "summary": "Delegated Calculation Plan",
            "steps": [
                {
                    "step_id": "step_del_45x8",
                    "action": "calculate 45 * 8",
                    "expected_outcome": "360",
                    "dependencies": [],
                    "authority_required": "HIGH"
                }
            ]
        }
        task_del = Task(
            user_id=user_del.id,
            title="Delegated 45*8 Task",
            prompt="Compute 45*8",
            status="HUMAN_REVIEW",
            plan=plan_del
        )
        db.add(task_del)
        db.commit()
        db.refresh(task_del)
        plan_del["task_id"] = task_del.id
        task_del.plan = plan_del
        db.commit()
        db.refresh(task_del)

        print("--- [1. DELEGATE: PostgreSQL BEFORE State] ---")
        print(f"Task ID: {task_del.id}")
        print(f"Tenant ID: {tenant_del}")
        print(f"Task Status: {task_del.status}")
        print(f"Task Plan: {json.dumps(task_del.plan, indent=2)}")
        print(f"Execution Result: {task_del.execution_result}")

        # Escalate
        item_del = manush_service.escalate_for_review(
            task_id=task_del.id,
            tenant_id=tenant_del,
            action_summary="calculate 45 * 8",
            step_id="step_del_45x8",
            risk_tier="HIGH",
            db_session=db,
            user_id=user_del.id
        )

        # Delegator submits DELEGATE
        sup_ctx = TenantContext(user_id=user_del.id, username="secops_supervisor", tenant_id=tenant_del, roles=["supervisor"])
        app.dependency_overrides[get_current_tenant] = lambda: sup_ctx
        client = TestClient(app)

        future_exp = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        del_sub = {
            "decision": "DELEGATE",
            "reviewer_id": "secops_supervisor",
            "justification": "Delegating calculation to math specialist",
            "signature": "hmac_sha256_sig_supervisor_lead",
            "delegate_id": "delegate_persist_user",
            "delegated_scope": ["calculate*"],
            "delegated_authority_tier": "HIGH",
            "delegation_expiry": future_exp
        }
        res_del_sub = client.post(f"/api/manush/reviews/{item_del.review_id}/resolve", json=del_sub)
        print(f"\nDELEGATE Submission HTTP Status: {res_del_sub.status_code}")

        # Delegate executes via POST /execute-delegated
        del_ctx = TenantContext(user_id=user_del.id, username="delegate_persist_user", tenant_id=tenant_del)
        app.dependency_overrides[get_current_tenant] = lambda: del_ctx

        tok_del = AuthorityToken.issue(
            tier=AuthorityTier.HIGH,
            scopes=["calculate*"],
            tenant_id=tenant_del
        )

        exec_del_payload = {
            "delegate_id": "delegate_persist_user",
            "authority_token": tok_del.model_dump()
        }
        res_del_exec = client.post(f"/api/manush/reviews/{item_del.review_id}/execute-delegated", json=exec_del_payload)
        print(f"DELEGATE Execute HTTP Status: {res_del_exec.status_code}")
        print(f"DELEGATE Execute Response: {json.dumps(res_del_exec.json(), indent=2)}")

        # Query PostgreSQL AFTER state
        db.refresh(task_del)
        print("\n--- [2. DELEGATE: PostgreSQL AFTER State] ---")
        print(f"Task ID: {task_del.id}")
        print(f"Tenant ID: {tenant_del}")
        print(f"Task Status: {task_del.status}")
        print(f"Task Plan: {json.dumps(task_del.plan, indent=2)}")
        print(f"Execution Result: {json.dumps(task_del.execution_result, indent=2)}")

        # Query CHITRA events for DELEGATE
        evts_del = db.query(ChitraEvent).filter(ChitraEvent.task_id == task_del.id).order_by(ChitraEvent.id.asc()).all()
        print(f"\n--- [3. DELEGATE: CHITRA Audit Trail (Events: {len(evts_del)})] ---")
        for i, ev in enumerate(evts_del):
            print(f"Event [{i+1}] {ev.event_id} | {ev.faculty} | {ev.event_type} | Outcome: {ev.outcome} | ThisHash: {ev.this_event_hash[:20]}... | PrevHash: {ev.prev_event_hash[:20]}...")
            if ev.faculty == "RACHIT":
                print(f"  RACHIT Decision: {json.dumps(ev.decision, indent=2)}")
                print(f"  RACHIT Outcome: {ev.outcome}")

        # Verify hash links for DELEGATE
        del_hash_ok = all(evts_del[i].prev_event_hash == evts_del[i-1].this_event_hash for i in range(1, len(evts_del)))
        print(f"DELEGATE Hash-Chain Continuity: {del_hash_ok}")

        # -------------------------------------------------------------
        # Part 2: AMEND Live Execution & PostgreSQL Task Persistence
        # -------------------------------------------------------------
        user_amend = db.query(User).filter(User.username == "amend_persist_user").first()
        if not user_amend:
            user_amend = User(username="amend_persist_user", hashed_password="hashed_pw_amend_222", is_active=True)
            db.add(user_amend)
            db.commit()
            db.refresh(user_amend)

        tenant_amend = f"tenant_{user_amend.id}"

        plan_amend = {
            "summary": "Original Multiplication Plan",
            "steps": [
                {
                    "step_id": "step_amend_calc",
                    "action": "calculate 5 * 5",
                    "expected_outcome": "25",
                    "dependencies": [],
                    "authority_required": "LOW"
                }
            ]
        }
        task_amend = Task(
            user_id=user_amend.id,
            title="Amend Calculation Task",
            prompt="Compute multiplication",
            status="HUMAN_REVIEW",
            plan=plan_amend
        )
        db.add(task_amend)
        db.commit()
        db.refresh(task_amend)
        plan_amend["task_id"] = task_amend.id
        task_amend.plan = plan_amend
        db.commit()
        db.refresh(task_amend)

        print("\n=================================================================")
        print("--- [4. AMEND: PostgreSQL BEFORE State] ---")
        print(f"Task ID: {task_amend.id}")
        print(f"Tenant ID: {tenant_amend}")
        print(f"Task Status: {task_amend.status}")
        print(f"Task Plan: {json.dumps(task_amend.plan, indent=2)}")
        print(f"Execution Result: {task_amend.execution_result}")

        # Escalate
        item_amend = manush_service.escalate_for_review(
            task_id=task_amend.id,
            tenant_id=tenant_amend,
            action_summary="calculate 5 * 5",
            step_id="step_amend_calc",
            risk_tier="HIGH",
            db_session=db,
            user_id=user_amend.id
        )

        # Reviewer submits AMEND with new calculation: calculate 12 * 12 (expected: 144)
        amend_ctx = TenantContext(user_id=user_amend.id, username="amend_persist_user", tenant_id=tenant_amend, roles=["supervisor"])
        app.dependency_overrides[get_current_tenant] = lambda: amend_ctx

        tok_amend = AuthorityToken.issue(
            tier=AuthorityTier.HIGH,
            scopes=["calculate*"],
            tenant_id=tenant_amend
        )

        amend_sub = {
            "decision": "AMEND",
            "reviewer_id": "amend_lead_supervisor",
            "justification": "Amending calculation to calculate 12 * 12",
            "signature": "hmac_sha256_sig_amend_lead",
            "amended_action": "calculate 12 * 12",
            "amended_parameters": {"expected_outcome": "144"},
            "authority_token": tok_amend.model_dump()
        }

        res_amend_sub = client.post(f"/api/manush/reviews/{item_amend.review_id}/resolve", json=amend_sub)
        print(f"\nAMEND Resolve HTTP Status: {res_amend_sub.status_code}")
        print(f"AMEND Resolve Response: {json.dumps(res_amend_sub.json(), indent=2)}")

        # Query PostgreSQL AFTER state for AMEND
        db.refresh(task_amend)
        print("\n--- [5. AMEND: PostgreSQL AFTER State] ---")
        print(f"Task ID: {task_amend.id}")
        print(f"Tenant ID: {tenant_amend}")
        print(f"Task Status: {task_amend.status}")
        print(f"Task Plan: {json.dumps(task_amend.plan, indent=2)}")
        print(f"Execution Result: {json.dumps(task_amend.execution_result, indent=2)}")

        # Query CHITRA events for AMEND
        evts_amend = db.query(ChitraEvent).filter(ChitraEvent.task_id == task_amend.id).order_by(ChitraEvent.id.asc()).all()
        print(f"\n--- [6. AMEND: CHITRA Audit Trail (Events: {len(evts_amend)})] ---")
        for i, ev in enumerate(evts_amend):
            print(f"Event [{i+1}] {ev.event_id} | {ev.faculty} | {ev.event_type} | Outcome: {ev.outcome} | ThisHash: {ev.this_event_hash[:20]}... | PrevHash: {ev.prev_event_hash[:20]}...")
            if ev.faculty == "RACHIT":
                print(f"  RACHIT Decision: {json.dumps(ev.decision, indent=2)}")
                print(f"  RACHIT Outcome: {ev.outcome}")

        # Verify hash links for AMEND
        amend_hash_ok = all(evts_amend[i].prev_event_hash == evts_amend[i-1].this_event_hash for i in range(1, len(evts_amend)))
        print(f"AMEND Hash-Chain Continuity: {amend_hash_ok}")

        # -------------------------------------------------------------
        # Part 3: Negative DB Persistence Failure (Fail-Closed)
        # -------------------------------------------------------------
        print("\n=================================================================")
        print("--- [7. Negative Test: DB Persistence Failure Fails Closed] ---")
        neg_service = ManushOversightService()
        neg_item = neg_service.queue.enqueue_review(
            task_id=999999, # non-existent task id in DB
            tenant_id=tenant_del,
            action_summary="calculate 1+1",
            step_id="step_neg_persist"
        )
        neg_service.queue.submit_decision(
            review_id=neg_item.review_id,
            tenant_id=tenant_del,
            decision=HumanReviewDecision(
                reviewer_id="lead", decision=ReviewDecisionType.DELEGATE, justification="just", signature="sig_lead_12345", delegate_id="delegate_persist_user", delegated_authority_tier="HIGH"
            )
        )
        neg_plan = KarmaPlanDAG(task_id=999999, summary="p", steps=[KarmaStep(step_id="step_neg_persist", action="calculate 1+1", expected_outcome="2", dependencies=[])])
        ok_neg, rep_neg, msg_neg = neg_service.execute_delegated_review(
            review_id=neg_item.review_id,
            tenant_id=tenant_del,
            delegate_id="delegate_persist_user",
            plan=neg_plan,
            caller_authority=tok_del,
            db_session=db,
            user_id=user_del.id
        )
        print(f"Missing Task DB Sync: Success={ok_neg} | Message='{msg_neg}'")
        assert ok_neg is False, "Must fail closed if task persistence fails!"

    finally:
        app.dependency_overrides.clear()
        db.close()

if __name__ == "__main__":
    run_persistence_forensics()
