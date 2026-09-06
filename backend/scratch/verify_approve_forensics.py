import json
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.core.manush.decision import ReviewStatus, ReviewDecisionType, HumanReviewDecision
from app.core.manush.service import manush_service
from app.core.tenant import TenantContext, get_current_tenant
from main import app

def run_approve_live_forensics():
    db = SessionLocal()
    print("=================================================================")
    print("=== LIVE FORENSIC EVIDENCE: APPROVE RESOLUTION & PERSISTENCE ===")
    print("=================================================================\n")
    
    try:
        user_app = db.query(User).filter(User.username == "approve_persist_user").first()
        if not user_app:
            user_app = User(username="approve_persist_user", hashed_password="hashed_pw_app_333", is_active=True)
            db.add(user_app)
            db.commit()
            db.refresh(user_app)

        tenant_app = f"tenant_{user_app.id}"

        plan_app = {
            "summary": "Approve Calculation Plan",
            "steps": [
                {
                    "step_id": "step_app_calc",
                    "action": "calculate 99 * 2",
                    "expected_outcome": "198",
                    "dependencies": [],
                    "authority_required": "LOW"
                }
            ]
        }
        task_app = Task(
            user_id=user_app.id,
            title="Approve Calculation Task",
            prompt="Compute 99*2",
            status="HUMAN_REVIEW",
            plan=plan_app
        )
        db.add(task_app)
        db.commit()
        db.refresh(task_app)
        plan_app["task_id"] = task_app.id
        task_app.plan = plan_app
        db.commit()
        db.refresh(task_app)

        print("--- [1. APPROVE: PostgreSQL BEFORE State] ---")
        print(f"Task ID: {task_app.id}")
        print(f"Tenant ID: {tenant_app}")
        print(f"Task Status: {task_app.status}")
        print(f"Execution Result: {task_app.execution_result}")
        print(f"Task Plan: {json.dumps(task_app.plan, indent=2)}")

        # Escalate
        item_app = manush_service.escalate_for_review(
            task_id=task_app.id,
            tenant_id=tenant_app,
            action_summary="calculate 99 * 2",
            step_id="step_app_calc",
            risk_tier="HIGH",
            db_session=db,
            user_id=user_app.id
        )

        # Reviewer submits APPROVE
        app_ctx = TenantContext(user_id=user_app.id, username="approve_supervisor", tenant_id=tenant_app, roles=["supervisor"])
        app.dependency_overrides[get_current_tenant] = lambda: app_ctx
        client = TestClient(app)

        app_payload = {
            "decision": "APPROVE",
            "reviewer_id": "approve_lead_supervisor",
            "justification": "Calculation action verified and authorized by supervisor",
            "signature": "hmac_sha256_sig_approve_lead_123"
        }

        res_app = client.post(f"/api/manush/reviews/{item_app.review_id}/resolve", json=app_payload)
        print(f"\nAPPROVE Resolve HTTP Status: {res_app.status_code}")
        print(f"APPROVE Resolve Response: {json.dumps(res_app.json(), indent=2)}")

        # Query PostgreSQL AFTER state
        db.refresh(task_app)
        print("\n--- [2. APPROVE: PostgreSQL AFTER State] ---")
        print(f"Task ID: {task_app.id}")
        print(f"Tenant ID: {tenant_app}")
        print(f"Task Status: {task_app.status}")
        print(f"Execution Result: {task_app.execution_result}")

        # Query CHITRA events for APPROVE
        evts_app = db.query(ChitraEvent).filter(ChitraEvent.task_id == task_app.id).order_by(ChitraEvent.id.asc()).all()
        print(f"\n--- [3. APPROVE: CHITRA Audit Trail (Events: {len(evts_app)})] ---")
        for i, ev in enumerate(evts_app):
            print(f"Event [{i+1}] {ev.event_id} | {ev.faculty} | {ev.event_type} | Outcome: {ev.outcome} | Confidence: {ev.confidence} | ThisHash: {ev.this_event_hash[:20]}... | PrevHash: {ev.prev_event_hash[:20]}...")
            if ev.faculty == "MANUSH":
                print(f"  MANUSH Decision: {json.dumps(ev.decision, indent=2)}")

        app_hash_ok = all(evts_app[i].prev_event_hash == evts_app[i-1].this_event_hash for i in range(1, len(evts_app)))
        print(f"APPROVE Hash-Chain Continuity: {app_hash_ok}")

    finally:
        app.dependency_overrides.clear()
        db.close()

if __name__ == "__main__":
    run_approve_live_forensics()
