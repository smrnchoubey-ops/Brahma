import json
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database import SessionLocal, engine
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.core.manush.decision import ReviewStatus, ReviewDecisionType, HumanReviewDecision
from app.core.manush.service import manush_service
from app.core.tenant import TenantContext, get_current_tenant
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
from app.core.maryada.token import AuthorityToken
from app.core.maryada.verdict import AuthorityTier
from main import app

def run_clean_positive_flow():
    db = SessionLocal()
    try:
        # 1. Setup user & aligned tenant
        username = "math_delegate_euler"
        user = db.query(User).filter(User.username == username).first()
        if not user:
            user = User(username=username, hashed_password="hashed_pw_euler_999", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)

        # EXACT ALIGNED TENANT: tenant_{user.id}
        tenant_id = f"tenant_{user.id}"
        print(f"=== ALIGNED TENANT IDENTIFIER: {tenant_id} ===")
        print(f"User ID: {user.id}, Username: {user.username}")

        # 2. Setup initial task
        plan_dict = {
            "summary": "Clean Positive Delegated Calc Task",
            "steps": [
                {
                    "step_id": "step_clean_math_01",
                    "action": "calculate 45 * 8",
                    "expected_outcome": "360",
                    "dependencies": [],
                    "authority_required": "HIGH"
                }
            ]
        }
        task = Task(
            user_id=user.id,
            title="Clean Delegated Computation Task",
            prompt="Compute 45 * 8 via authorized delegate",
            status="HUMAN_REVIEW",
            plan=plan_dict
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        plan_dict["task_id"] = task.id
        task.plan = plan_dict
        db.commit()
        db.refresh(task)

        # 3. Print BEFORE state
        print("\n--- [1. POSTGRESQL TASK BEFORE STATE] ---")
        print(f"task.id: {task.id}")
        print(f"tenant_id: {tenant_id}")
        print(f"task.status: {task.status}")
        print(f"task.plan: {json.dumps(task.plan, indent=2)}")
        print(f"task.execution_result: {task.execution_result}")

        # 4. Escalate for review
        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=tenant_id,
            action_summary="calculate 45 * 8",
            step_id="step_clean_math_01",
            risk_tier="HIGH",
            db_session=db,
            user_id=user.id
        )
        print(f"\nEscalated Review Item ID: {review_item.review_id}")

        # 5. Delegator submits DELEGATE decision
        supervisor_ctx = TenantContext(user_id=user.id, username="forensic_supervisor_lead", tenant_id=tenant_id, roles=["supervisor"])
        app.dependency_overrides[get_current_tenant] = lambda: supervisor_ctx
        client = TestClient(app)

        future_exp = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        delegate_submission = {
            "decision": "DELEGATE",
            "reviewer_id": "forensic_supervisor_lead",
            "justification": "Delegating multiplication 45*8 to math specialist euler",
            "signature": "hmac_sha256_sig_supervisor_lead_secops",
            "delegate_id": "math_delegate_euler",
            "delegated_scope": ["calculate*"],
            "delegated_authority_tier": "HIGH",
            "delegation_expiry": future_exp
        }

        res_del = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=delegate_submission)
        print("\n--- [2. HTTP DELEGATE SUBMISSION RESULT] ---")
        print(f"Status Code: {res_del.status_code}")
        print(f"Response Body: {json.dumps(res_del.json(), indent=2)}")

        # 6. Delegate issues signed AuthorityToken with matching tenant
        delegate_tok = AuthorityToken.issue(
            tier=AuthorityTier.HIGH,
            scopes=["calculate*"],
            tenant_id=tenant_id
        )

        print("\n--- [3. AUTHORITY TOKEN VERIFICATION EVIDENCE] ---")
        print(f"token_id: {delegate_tok.token_id}")
        print(f"tier: {delegate_tok.tier.value}")
        print(f"tenant_id: {delegate_tok.tenant_id}")
        print(f"scopes: {delegate_tok.scopes}")
        print(f"issued_at: {delegate_tok.issued_at}")
        print(f"expires_at: {delegate_tok.expires_at}")
        print(f"signature_valid: {delegate_tok.verify_signature()}")
        print(f"is_expired: {delegate_tok.is_expired()}")
        print(f"is_not_yet_valid: {delegate_tok.is_not_yet_valid()}")

        # 7. Authenticated delegate execution via HTTP POST /execute-delegated
        delegate_ctx = TenantContext(user_id=user.id, username="math_delegate_euler", tenant_id=tenant_id)
        app.dependency_overrides[get_current_tenant] = lambda: delegate_ctx

        exec_payload = {
            "delegate_id": "math_delegate_euler",
            "authority_token": delegate_tok.model_dump()
        }

        res_exec = client.post(f"/api/manush/reviews/{review_item.review_id}/execute-delegated", json=exec_payload)
        print("\n--- [4. HTTP DELEGATED EXECUTION RESULT] ---")
        print(f"Status Code: {res_exec.status_code}")
        print(f"Response Body: {json.dumps(res_exec.json(), indent=2)}")

        # 8. Query PostgreSQL AFTER state
        db.refresh(task)
        print("\n--- [5. POSTGRESQL TASK AFTER STATE] ---")
        print(f"task.id: {task.id}")
        print(f"tenant_id: {tenant_id}")
        print(f"task.status: {task.status}")
        print(f"task.plan: {json.dumps(task.plan, indent=2)}")
        print(f"task.execution_result: {task.execution_result}")

        # 9. Query ALL CHITRA events for this task
        chitra_events = db.query(ChitraEvent).filter(
            ChitraEvent.task_id == task.id
        ).order_by(ChitraEvent.id.asc()).all()

        print(f"\n--- [6. COMPLETE CHITRA AUDIT TRAIL (Total Events: {len(chitra_events)})] ---")
        for i, ev in enumerate(chitra_events):
            print(f"\n=== CHITRA EVENT [{i+1}] ===")
            print(f"event_id: {ev.event_id}")
            print(f"timestamp: {ev.timestamp.isoformat()}")
            print(f"faculty: {ev.faculty}")
            print(f"event_type: {ev.event_type}")
            print(f"outcome: {ev.outcome}")
            print(f"confidence: {ev.confidence}")
            print(f"prev_event_hash: {ev.prev_event_hash}")
            print(f"this_event_hash: {ev.this_event_hash}")
            print(f"signature: {ev.signature}")
            print(f"decision: {json.dumps(ev.decision, indent=2)}")

        # 10. Explicit Hash-Chain Continuity Verification
        print("\n--- [7. EXPLICIT HASH-CHAIN CONTINUITY VERIFICATION] ---")
        for i in range(1, len(chitra_events)):
            prev_ev = chitra_events[i-1]
            curr_ev = chitra_events[i]
            matches = (curr_ev.prev_event_hash == prev_ev.this_event_hash)
            print(f"Link [{i}] -> [{i+1}]: {prev_ev.this_event_hash[:24]}... == {curr_ev.prev_event_hash[:24]}... | MATCH = {matches}")

    finally:
        app.dependency_overrides.clear()
        db.close()

if __name__ == "__main__":
    run_clean_positive_flow()
