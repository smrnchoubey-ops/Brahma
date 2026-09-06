import json
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.database import SessionLocal, engine
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.core.manush.decision import ReviewStatus, ReviewDecisionType, HumanReviewDecision
from app.core.manush.review_queue import ManushReviewQueue
from app.core.manush.service import manush_service, ManushOversightService
from app.core.tenant import TenantContext, get_current_tenant
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
from app.core.maryada.token import AuthorityToken
from main import app

def run_forensic_capture():
    db = SessionLocal()
    print("=== LIVE FORENSIC VERIFICATION SUITE FOR MANUSH DELEGATE ===")
    
    try:
        # 1. Setup real user & tenant in PostgreSQL
        user = db.query(User).filter(User.username == "forensic_supervisor").first()
        if not user:
            user = User(username="forensic_supervisor", hashed_password="hashed_pw_xyz", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)

        tenant_id = f"tenant_forensic_{user.id}"
        
        # 2. Setup initial paused task in PostgreSQL
        plan_dict = {
            "task_id": 0,
            "summary": "Forensic Delegated Computation Task",
            "steps": [
                {
                    "step_id": "step_del_math_01",
                    "action": "calculate 45 * 8",
                    "expected_outcome": "360",
                    "dependencies": [],
                    "authority_required": "MEDIUM"
                }
            ]
        }
        
        task = Task(
            user_id=user.id,
            title="Forensic Delegation Task",
            prompt="Compute 45 * 8 via delegated specialist",
            status="HUMAN_REVIEW",
            plan=plan_dict
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        
        # Update plan with real task.id
        plan_dict["task_id"] = task.id
        task.plan = plan_dict
        db.commit()
        db.refresh(task)
        
        print("\n--- [A. PostgreSQL BEFORE State] ---")
        print(f"Task ID: {task.id}")
        print(f"User ID: {task.user_id}")
        print(f"Status: {task.status}")
        print(f"Plan: {json.dumps(task.plan, indent=2)}")
        
        # 3. Escalate for human review
        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=tenant_id,
            action_summary="calculate 45 * 8",
            step_id="step_del_math_01",
            risk_tier="HIGH",
            db_session=db,
            user_id=user.id
        )
        print(f"\nEscalated Review Item ID: {review_item.review_id}")
        print(f"Queue Status: {review_item.status.value}")
        
        # 4. HTTP POST /resolve (DELEGATE)
        tenant_ctx = TenantContext(user_id=user.id, username=user.username, tenant_id=tenant_id, roles=["supervisor"])
        app.dependency_overrides[get_current_tenant] = lambda: tenant_ctx
        client = TestClient(app)
        
        future_exp = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
        delegate_submission_payload = {
            "decision": "DELEGATE",
            "reviewer_id": "forensic_supervisor_lead",
            "justification": "Delegating multiplication calculation to math specialist agent/reviewer",
            "signature": "hmac_sha256_sig_supervisor_lead_secops",
            "delegate_id": "math_specialist_dr_euler",
            "delegated_scope": ["calculate*"],
            "delegated_authority_tier": "HIGH",
            "delegation_expiry": future_exp
        }
        
        print("\n--- [B. HTTP DELEGATE Submission Request] ---")
        print(f"POST /api/manush/reviews/{review_item.review_id}/resolve")
        print(f"Payload: {json.dumps(delegate_submission_payload, indent=2)}")
        
        res_del = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=delegate_submission_payload)
        print(f"\nHTTP Status: {res_del.status_code}")
        print(f"Response Body: {json.dumps(res_del.json(), indent=2)}")
        
        # 5. PostgreSQL State AFTER DELEGATE Submission
        db.refresh(task)
        item_after_del = manush_service.queue.get_item(review_item.review_id, tenant_id)
        print("\n--- [C. State AFTER DELEGATE Submission] ---")
        print(f"Queue Item Status: {item_after_del.status.value}")
        print(f"Assigned Delegate ID: {item_after_del.delegate_id}")
        print(f"Delegated Scope: {item_after_del.delegated_scope}")
        print(f"Delegated Authority Tier: {item_after_del.delegated_authority_tier}")
        print(f"Delegation Expiry: {item_after_del.delegation_expiry}")
        
        # Query CHITRA PostgreSQL events
        chitra_events = db.query(ChitraEvent).filter(
            ChitraEvent.task_id == task.id,
            ChitraEvent.faculty == "MANUSH"
        ).order_by(ChitraEvent.id.desc()).all()
        
        evt_delegate = None
        for ev in chitra_events:
            out = ev.outcome
            if isinstance(out, str) and "DELEGATED_BY_HUMAN" in out:
                evt_delegate = ev
                break
            elif isinstance(out, dict) and out.get("status") == "DELEGATED_BY_HUMAN":
                evt_delegate = ev
                break
            elif ev.decision and isinstance(ev.decision, dict) and ev.decision.get("decision") == "DELEGATE":
                evt_delegate = ev
                break
        
        print("\n--- [D. Real CHITRA Event: DELEGATE Decision] ---")
        if evt_delegate:
            print(f"Event ID: {evt_delegate.event_id}")
            print(f"Timestamp: {evt_delegate.timestamp}")
            print(f"Faculty: {evt_delegate.faculty}")
            print(f"Event Type: {evt_delegate.event_type}")
            print(f"Outcome: {evt_delegate.outcome}")
            print(f"Confidence: {evt_delegate.confidence}")
            print(f"Previous Hash: {evt_delegate.prev_event_hash}")
            print(f"This Event Hash: {evt_delegate.this_event_hash}")
            print(f"Signature: {evt_delegate.signature}")
            print(f"Decision Payload: {json.dumps(evt_delegate.decision, indent=2)}")
        
        # 6. HTTP POST /execute-delegated by the authorized delegate with verified identity & signed AuthorityToken
        euler_ctx = TenantContext(user_id=user.id, username="math_specialist_dr_euler", tenant_id=tenant_id)
        app.dependency_overrides[get_current_tenant] = lambda: euler_ctx

        from app.core.maryada.verdict import AuthorityTier
        euler_token = AuthorityToken.issue(
            tier=AuthorityTier.HIGH,
            scopes=["calculate*"],
            tenant_id=tenant_id
        )

        exec_payload = {
            "delegate_id": "math_specialist_dr_euler",
            "authority_token": euler_token.model_dump()
        }
        
        print("\n--- [E. HTTP Delegate Execution Request] ---")
        print(f"POST /api/manush/reviews/{review_item.review_id}/execute-delegated")
        print(f"Payload: {json.dumps(exec_payload, indent=2)}")
        
        res_exec = client.post(f"/api/manush/reviews/{review_item.review_id}/execute-delegated", json=exec_payload)
        print(f"\nHTTP Status: {res_exec.status_code}")
        print(f"Response Body: {json.dumps(res_exec.json(), indent=2)}")
        
        # 7. PostgreSQL Final State
        db.refresh(task)
        print("\n--- [F. PostgreSQL Final State] ---")
        print(f"Task Status: {task.status}")
        print(f"Task Execution Result: {task.execution_result}")
        
        # Query CHITRA events for delegated execution
        all_evts = db.query(ChitraEvent).filter(
            ChitraEvent.task_id == task.id
        ).order_by(ChitraEvent.id.asc()).all()
        print(f"\nTotal CHITRA Events for Task {task.id}: {len(all_evts)}")
        for i, ev in enumerate(all_evts):
            print(f"  [{i+1}] {ev.event_id} | Faculty: {ev.faculty} | Type: {ev.event_type} | Outcome: {ev.outcome} | Hash: {ev.this_event_hash[:20]}... | Sig: {ev.signature[:20]}...")

        # 8. Negative Security Proving Suite (Zero Tool Invocations)
        print("\n--- [G. Negative Security Invariant Verification (Zero Invocations)] ---")
        
        # (1) Missing AuthorityToken
        res_no_tok = client.post(f"/api/manush/reviews/{review_item.review_id}/execute-delegated", json={"delegate_id": "math_specialist_dr_euler"})
        print(f"1. Missing AuthorityToken: Status {res_no_tok.status_code} | Msg: {res_no_tok.json().get('detail')}")

        # (2) Invalid Signature AuthorityToken
        bad_sig_tok = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id=tenant_id)
        bad_sig_tok.signature = "hmac-sha256:forged_invalid_signature"
        res_bad_sig = client.post(f"/api/manush/reviews/{review_item.review_id}/execute-delegated", json={"delegate_id": "math_specialist_dr_euler", "authority_token": bad_sig_tok.model_dump()})
        print(f"2. Invalid Signature Token: Status {res_bad_sig.status_code} | Msg: {res_bad_sig.json().get('message') or res_bad_sig.json().get('detail')}")

        # (3) Unauthorized delegate identity mismatch
        eve_ctx = TenantContext(user_id=user.id, username="attacker_eve", tenant_id=tenant_id)
        app.dependency_overrides[get_current_tenant] = lambda: eve_ctx
        res_unauth = client.post(f"/api/manush/reviews/{review_item.review_id}/execute-delegated", json={"delegate_id": "attacker_eve", "authority_token": euler_token.model_dump()})
        print(f"3. Unauthorized Delegate ('attacker_eve'): Status {res_unauth.status_code} | Msg: {res_unauth.json().get('message') or res_unauth.json().get('detail')}")
        
        # (4) Cross-tenant request
        eve_tenant_ctx = TenantContext(user_id=8888, username="math_specialist_dr_euler", tenant_id="tenant_rogue_8888")
        app.dependency_overrides[get_current_tenant] = lambda: eve_tenant_ctx
        res_cross = client.post(f"/api/manush/reviews/{review_item.review_id}/execute-delegated", json={"delegate_id": "math_specialist_dr_euler", "authority_token": euler_token.model_dump()})
        print(f"4. Cross-Tenant Attempt (tenant_rogue_8888): Status {res_cross.status_code} | Msg: {res_cross.json().get('detail')}")
        
        # Restore tenant
        app.dependency_overrides[get_current_tenant] = lambda: euler_ctx

        # (5) Finalized item retroactive delegation
        term_queue = ManushReviewQueue()
        term_item = term_queue.enqueue_review(task_id=999, tenant_id=tenant_id, action_summary="terminate_action")
        term_queue.submit_decision(term_item.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="lead_reviewer", decision=ReviewDecisionType.TERMINATE, justification="Hard stop", signature="valid_lead_sig_123"
        ))
        ok_retro, _, retro_msg = term_queue.submit_decision(term_item.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="lead_reviewer_2", decision=ReviewDecisionType.DELEGATE, justification="Retro delegate", signature="valid_lead_sig_456", delegate_id="bob"
        ))
        print(f"5. Retroactive Delegation on Terminated Item: Accepted={ok_retro} | Msg: {retro_msg}")

        # (6) Expired delegation
        exp_queue = ManushReviewQueue()
        exp_item = exp_queue.enqueue_review(task_id=998, tenant_id=tenant_id, action_summary="exp_action")
        ok_exp, _, exp_msg = exp_queue.submit_decision(exp_item.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Expired delegate", signature="valid_lead_sig_123",
            delegate_id="bob", delegation_expiry=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        ))
        print(f"6. Expired Delegation Submission: Accepted={ok_exp} | Msg: {exp_msg}")

        # (7) Caller Tier HIGH exceeding Delegation Ceiling LOW (HARD FAIL)
        ceil_service = ManushOversightService()
        ceil_item = ceil_service.queue.enqueue_review(task_id=997, tenant_id=tenant_id, action_summary="calculate 1+1", step_id="s_ceil")
        ceil_service.queue.submit_decision(ceil_item.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Del with LOW ceiling", signature="valid_lead_sig_123",
            delegate_id="bob", delegated_authority_tier="LOW"
        ))
        ceil_plan = KarmaPlanDAG(task_id=997, summary="Ceil", steps=[KarmaStep(step_id="s_ceil", action="calculate 1+1", expected_outcome="2", dependencies=[])])
        inv_count_ceil = 0
        class MockSpyExecutor:
            def execute_plan(self, *args, **kwargs):
                nonlocal inv_count_ceil
                inv_count_ceil += 1
                return {}
        tok_high = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id=tenant_id)
        ok_ceil, _, ceil_msg = ceil_service.execute_delegated_review(
            review_id=ceil_item.review_id, tenant_id=tenant_id, delegate_id="bob", plan=ceil_plan, caller_authority=tok_high, executor=MockSpyExecutor()
        )
        print(f"7. Caller Tier HIGH > Ceiling LOW (HARD FAIL): Success={ok_ceil} | Invocations={inv_count_ceil} | Msg: {ceil_msg}")

        # (8) Unauthorized Scope
        scope_service = ManushOversightService()
        scope_item = scope_service.queue.enqueue_review(task_id=996, tenant_id=tenant_id, action_summary="critical_delete", step_id="s_del")
        scope_service.queue.submit_decision(scope_item.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Delegate calc only", signature="valid_lead_sig_123",
            delegate_id="bob", delegated_scope=["calculate*"], delegated_authority_tier="HIGH"
        ))
        scope_plan = KarmaPlanDAG(
            task_id=996, summary="Delete plan",
            steps=[KarmaStep(step_id="s_del", action="critical_delete", expected_outcome="deleted", dependencies=[])]
        )
        inv_count = 0
        class MockSpyExecutor2:
            def execute_plan(self, *args, **kwargs):
                nonlocal inv_count
                inv_count += 1
                return {}
        tok_scope = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id=tenant_id)
        ok_scope, _, scope_msg = scope_service.execute_delegated_review(
            review_id=scope_item.review_id, tenant_id=tenant_id, delegate_id="bob", plan=scope_plan, caller_authority=tok_scope, executor=MockSpyExecutor2()
        )
        print(f"8. Unauthorized Scope ('critical_delete' vs 'calculate*'): Success={ok_scope} | Invocations={inv_count} | Msg: {scope_msg}")

        # (9) Target Action Requiring Higher Authority than Delegation
        auth_service = ManushOversightService()
        auth_item = auth_service.queue.enqueue_review(task_id=995, tenant_id=tenant_id, action_summary="super_admin_op", step_id="s_adm")
        auth_service.queue.submit_decision(auth_item.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="lead_reviewer", decision=ReviewDecisionType.DELEGATE, justification="Delegate with MEDIUM tier", signature="valid_lead_sig_123",
            delegate_id="bob", delegated_authority_tier="MEDIUM", delegated_scope=["super_admin_op"]
        ))
        auth_plan = KarmaPlanDAG(
            task_id=995, summary="Admin plan",
            steps=[KarmaStep(step_id="s_adm", action="super_admin_op", expected_outcome="done", dependencies=[], authority_required="CRITICAL")]
        )
        inv_count_auth = 0
        class MockSpyExecutor3:
            def execute_plan(self, *args, **kwargs):
                nonlocal inv_count_auth
                inv_count_auth += 1
                return {}
        tok_med = AuthorityToken.issue(tier=AuthorityTier.MEDIUM, scopes=["super_admin_op"], tenant_id=tenant_id)
        ok_auth, _, auth_msg = auth_service.execute_delegated_review(
            review_id=auth_item.review_id, tenant_id=tenant_id, delegate_id="bob", plan=auth_plan, caller_authority=tok_med, executor=MockSpyExecutor3()
        )
        print(f"9. Step Authority CRITICAL > Delegation Ceiling MEDIUM: Success={ok_auth} | Invocations={inv_count_auth} | Msg: {auth_msg}")

    finally:
        app.dependency_overrides.clear()
        db.close()

if __name__ == "__main__":
    run_forensic_capture()
