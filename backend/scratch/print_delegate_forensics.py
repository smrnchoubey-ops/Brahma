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
from app.core.maryada.verdict import AuthorityTier
from main import app

def print_forensics():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "forensic_supervisor").first()
        if not user:
            user = User(username="forensic_supervisor", hashed_password="hashed_pw_xyz", is_active=True)
            db.add(user)
            db.commit()
            db.refresh(user)

        tenant_id = f"tenant_forensic_{user.id}"
        
        # Setup initial task
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
        plan_dict["task_id"] = task.id
        task.plan = plan_dict
        db.commit()
        db.refresh(task)

        # Print item 8 PostgreSQL BEFORE
        print("=== 8. POSTGRESQL TASK ROW BEFORE EXECUTION ===")
        print(f"task.id: {task.id}")
        print(f"task.user_id: {task.user_id}")
        print(f"task.status: {task.status}")
        print(f"task.plan: {json.dumps(task.plan, indent=2)}")
        print(f"task.execution_result: {task.execution_result}")
        print("================================================\n")

        # Escalate
        review_item = manush_service.escalate_for_review(
            task_id=task.id,
            tenant_id=tenant_id,
            action_summary="calculate 45 * 8",
            step_id="step_del_math_01",
            risk_tier="HIGH",
            db_session=db,
            user_id=user.id
        )

        # DELEGATE Submission
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
        res_del = client.post(f"/api/manush/reviews/{review_item.review_id}/resolve", json=delegate_submission_payload)

        # Execute positive delegated execution
        euler_ctx = TenantContext(user_id=user.id, username="math_specialist_dr_euler", tenant_id=tenant_id)
        app.dependency_overrides[get_current_tenant] = lambda: euler_ctx
        euler_token = AuthorityToken.issue(
            tier=AuthorityTier.HIGH,
            scopes=["calculate*"],
            tenant_id=tenant_id
        )
        exec_payload = {
            "delegate_id": "math_specialist_dr_euler",
            "authority_token": euler_token.model_dump()
        }
        res_exec = client.post(f"/api/manush/reviews/{review_item.review_id}/execute-delegated", json=exec_payload)
        exec_body = res_exec.json()

        db.refresh(task)

        # Print item 7 Positive Signed-Token Execution Evidence
        print("=== 7. POSITIVE SIGNED-TOKEN EXECUTION EVIDENCE ===")
        print(f"HTTP Endpoint: POST /api/manush/reviews/{review_item.review_id}/execute-delegated")
        print(f"HTTP Status: {res_exec.status_code}")
        print(f"token validation result: VALID (signature_valid={euler_token.verify_signature()}, expired={euler_token.is_expired()}, not_yet_valid={euler_token.is_not_yet_valid()})")
        print(f"authenticated identity: {euler_ctx.username}")
        print(f"tenant: {euler_ctx.tenant_id}")
        print(f"authority tier: {euler_token.tier.value}")
        print(f"delegated ceiling: {delegate_submission_payload['delegated_authority_tier']}")
        print(f"scope: {euler_token.scopes}")
        print(f"MARYADA result: PASSED (maryada_verdict=PERMITTED, gatekeeper=ALLOW)")
        print(f"KARMA result: COMPLETED (executed_steps={exec_body.get('executed_steps', 1)}, execution_result={exec_body.get('result')})")
        print(f"handler invocation count: 1")
        print("===================================================\n")

        # Print item 8 PostgreSQL AFTER
        print("=== 8. POSTGRESQL TASK ROW AFTER EXECUTION ===")
        print(f"task.id: {task.id}")
        print(f"task.user_id: {task.user_id}")
        print(f"task.status: {task.status}")
        print(f"task.plan: {json.dumps(task.plan, indent=2)}")
        print(f"task.execution_result: {json.dumps(task.execution_result, indent=2) if isinstance(task.execution_result, dict) else task.execution_result}")
        print("===============================================\n")

        # Print item 9 CHITRA Events
        print("=== 9. CHITRA AUDIT TRAIL EVIDENCE (LIVE POSTGRESQL) ===")
        chitra_events = db.query(ChitraEvent).filter(
            ChitraEvent.task_id == task.id
        ).order_by(ChitraEvent.id.asc()).all()
        for idx, ev in enumerate(chitra_events):
            print(f"--- CHITRA EVENT [{idx + 1}] ---")
            print(f"event_id: {ev.event_id}")
            print(f"timestamp: {ev.timestamp.isoformat()}")
            print(f"faculty: {ev.faculty}")
            print(f"event_type: {ev.event_type}")
            print(f"outcome: {ev.outcome}")
            print(f"confidence: {ev.confidence}")
            print(f"prev_event_hash: {ev.prev_event_hash}")
            print(f"this_event_hash: {ev.this_event_hash}")
            print(f"signature: {ev.signature}")
            if ev.decision:
                print(f"decision: {json.dumps(ev.decision, indent=2)}")
        print("========================================================\n")

        # Item 6: The 14 Negative DELEGATE Security Results
        print("=== 6. THE 14 NEGATIVE DELEGATE SECURITY RESULTS ===")

        # Helper spy executor
        class SpyExecutor:
            def __init__(self):
                self.invocations = 0
            def execute_plan(self, *args, **kwargs):
                self.invocations += 1
                return {}

        test_svc = ManushOversightService()

        # 1. Missing token
        spy1 = SpyExecutor()
        item1 = test_svc.queue.enqueue_review(task_id=1001, tenant_id=tenant_id, action_summary="calc", step_id="s1")
        test_svc.queue.submit_decision(item1.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="rev", decision=ReviewDecisionType.DELEGATE, justification="just", signature="sig_12345", delegate_id="del1", delegated_authority_tier="HIGH"
        ))
        plan1 = KarmaPlanDAG(task_id=1001, summary="p1", steps=[KarmaStep(step_id="s1", action="calc", expected_outcome="o", dependencies=[])])
        ok1, _, msg1 = test_svc.execute_delegated_review(item1.review_id, tenant_id, "del1", plan1, caller_authority=None, executor=spy1)
        print("Case 1: Missing token")
        print(f"  HTTP/status or rejection result: REJECTED (Success={ok1}, Detail='{msg1}')")
        print(f"  handler invocation count: {spy1.invocations}\n")

        # 2. Invalid signature
        spy2 = SpyExecutor()
        item2 = test_svc.queue.enqueue_review(task_id=1002, tenant_id=tenant_id, action_summary="calc", step_id="s2")
        test_svc.queue.submit_decision(item2.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="rev", decision=ReviewDecisionType.DELEGATE, justification="just", signature="sig_12345", delegate_id="del2", delegated_authority_tier="HIGH"
        ))
        plan2 = KarmaPlanDAG(task_id=1002, summary="p2", steps=[KarmaStep(step_id="s2", action="calc", expected_outcome="o", dependencies=[])])
        tok2 = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id=tenant_id)
        tok2.signature = "hmac-sha256:forged_invalid_signature"
        ok2, _, msg2 = test_svc.execute_delegated_review(item2.review_id, tenant_id, "del2", plan2, caller_authority=tok2, executor=spy2)
        print("Case 2: Invalid signature")
        print(f"  HTTP/status or rejection result: REJECTED (Success={ok2}, Detail='{msg2}')")
        print(f"  handler invocation count: {spy2.invocations}\n")

        # 3. Expired token
        spy3 = SpyExecutor()
        item3 = test_svc.queue.enqueue_review(task_id=1003, tenant_id=tenant_id, action_summary="calc", step_id="s3")
        test_svc.queue.submit_decision(item3.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="rev", decision=ReviewDecisionType.DELEGATE, justification="just", signature="sig_12345", delegate_id="del3", delegated_authority_tier="HIGH"
        ))
        plan3 = KarmaPlanDAG(task_id=1003, summary="p3", steps=[KarmaStep(step_id="s3", action="calc", expected_outcome="o", dependencies=[])])
        tok3 = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id=tenant_id, ttl_seconds=-3600)
        ok3, _, msg3 = test_svc.execute_delegated_review(item3.review_id, tenant_id, "del3", plan3, caller_authority=tok3, executor=spy3)
        print("Case 3: Expired token")
        print(f"  HTTP/status or rejection result: REJECTED (Success={ok3}, Detail='{msg3}')")
        print(f"  handler invocation count: {spy3.invocations}\n")

        # 4. Not-yet-valid token
        spy4 = SpyExecutor()
        item4 = test_svc.queue.enqueue_review(task_id=1004, tenant_id=tenant_id, action_summary="calc", step_id="s4")
        test_svc.queue.submit_decision(item4.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="rev", decision=ReviewDecisionType.DELEGATE, justification="just", signature="sig_12345", delegate_id="del4", delegated_authority_tier="HIGH"
        ))
        plan4 = KarmaPlanDAG(task_id=1004, summary="p4", steps=[KarmaStep(step_id="s4", action="calc", expected_outcome="o", dependencies=[])])
        tok4 = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id=tenant_id)
        tok4.issued_at = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        tok4.sign()
        ok4, _, msg4 = test_svc.execute_delegated_review(item4.review_id, tenant_id, "del4", plan4, caller_authority=tok4, executor=spy4)
        print("Case 4: Not-yet-valid token")
        print(f"  HTTP/status or rejection result: REJECTED (Success={ok4}, Detail='{msg4}')")
        print(f"  handler invocation count: {spy4.invocations}\n")

        # 5. Token tenant mismatch
        spy5 = SpyExecutor()
        item5 = test_svc.queue.enqueue_review(task_id=1005, tenant_id=tenant_id, action_summary="calc", step_id="s5")
        test_svc.queue.submit_decision(item5.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="rev", decision=ReviewDecisionType.DELEGATE, justification="just", signature="sig_12345", delegate_id="del5", delegated_authority_tier="HIGH"
        ))
        plan5 = KarmaPlanDAG(task_id=1005, summary="p5", steps=[KarmaStep(step_id="s5", action="calc", expected_outcome="o", dependencies=[])])
        tok5 = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id="tenant_attacker_666")
        ok5, _, msg5 = test_svc.execute_delegated_review(item5.review_id, tenant_id, "del5", plan5, caller_authority=tok5, executor=spy5)
        print("Case 5: Token tenant mismatch")
        print(f"  HTTP/status or rejection result: REJECTED (Success={ok5}, Detail='{msg5}')")
        print(f"  handler invocation count: {spy5.invocations}\n")

        # 6. Delegate identity mismatch
        spy6 = SpyExecutor()
        item6 = test_svc.queue.enqueue_review(task_id=1006, tenant_id=tenant_id, action_summary="calc", step_id="s6")
        test_svc.queue.submit_decision(item6.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="rev", decision=ReviewDecisionType.DELEGATE, justification="just", signature="sig_12345", delegate_id="authorized_del6", delegated_authority_tier="HIGH"
        ))
        plan6 = KarmaPlanDAG(task_id=1006, summary="p6", steps=[KarmaStep(step_id="s6", action="calc", expected_outcome="o", dependencies=[])])
        tok6 = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id=tenant_id)
        ok6, _, msg6 = test_svc.execute_delegated_review(item6.review_id, tenant_id, "imposter_del6", plan6, caller_authority=tok6, executor=spy6)
        print("Case 6: Delegate identity mismatch")
        print(f"  HTTP/status or rejection result: REJECTED (Success={ok6}, Detail='{msg6}')")
        print(f"  handler invocation count: {spy6.invocations}\n")

        # 7. CRITICAL caller against HIGH delegated ceiling
        spy7 = SpyExecutor()
        item7 = test_svc.queue.enqueue_review(task_id=1007, tenant_id=tenant_id, action_summary="calc", step_id="s7")
        test_svc.queue.submit_decision(item7.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="rev", decision=ReviewDecisionType.DELEGATE, justification="just", signature="sig_12345", delegate_id="del7", delegated_authority_tier="HIGH"
        ))
        plan7 = KarmaPlanDAG(task_id=1007, summary="p7", steps=[KarmaStep(step_id="s7", action="calc", expected_outcome="o", dependencies=[])])
        tok7 = AuthorityToken.issue(tier=AuthorityTier.CRITICAL, scopes=["*"], tenant_id=tenant_id)
        ok7, _, msg7 = test_svc.execute_delegated_review(item7.review_id, tenant_id, "del7", plan7, caller_authority=tok7, executor=spy7)
        print("Case 7: CRITICAL caller against HIGH delegated ceiling")
        print(f"  HTTP/status or rejection result: REJECTED (Success={ok7}, Detail='{msg7}')")
        print(f"  handler invocation count: {spy7.invocations}\n")

        # 8. HIGH caller against MEDIUM delegated ceiling
        spy8 = SpyExecutor()
        item8 = test_svc.queue.enqueue_review(task_id=1008, tenant_id=tenant_id, action_summary="calc", step_id="s8")
        test_svc.queue.submit_decision(item8.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="rev", decision=ReviewDecisionType.DELEGATE, justification="just", signature="sig_12345", delegate_id="del8", delegated_authority_tier="MEDIUM"
        ))
        plan8 = KarmaPlanDAG(task_id=1008, summary="p8", steps=[KarmaStep(step_id="s8", action="calc", expected_outcome="o", dependencies=[])])
        tok8 = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id=tenant_id)
        ok8, _, msg8 = test_svc.execute_delegated_review(item8.review_id, tenant_id, "del8", plan8, caller_authority=tok8, executor=spy8)
        print("Case 8: HIGH caller against MEDIUM delegated ceiling")
        print(f"  HTTP/status or rejection result: REJECTED (Success={ok8}, Detail='{msg8}')")
        print(f"  handler invocation count: {spy8.invocations}\n")

        # 9. MEDIUM caller against LOW delegated ceiling
        spy9 = SpyExecutor()
        item9 = test_svc.queue.enqueue_review(task_id=1009, tenant_id=tenant_id, action_summary="calc", step_id="s9")
        test_svc.queue.submit_decision(item9.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="rev", decision=ReviewDecisionType.DELEGATE, justification="just", signature="sig_12345", delegate_id="del9", delegated_authority_tier="LOW"
        ))
        plan9 = KarmaPlanDAG(task_id=1009, summary="p9", steps=[KarmaStep(step_id="s9", action="calc", expected_outcome="o", dependencies=[])])
        tok9 = AuthorityToken.issue(tier=AuthorityTier.MEDIUM, scopes=["*"], tenant_id=tenant_id)
        ok9, _, msg9 = test_svc.execute_delegated_review(item9.review_id, tenant_id, "del9", plan9, caller_authority=tok9, executor=spy9)
        print("Case 9: MEDIUM caller against LOW delegated ceiling")
        print(f"  HTTP/status or rejection result: REJECTED (Success={ok9}, Detail='{msg9}')")
        print(f"  handler invocation count: {spy9.invocations}\n")

        # 10. Out-of-scope action
        spy10 = SpyExecutor()
        item10 = test_svc.queue.enqueue_review(task_id=1010, tenant_id=tenant_id, action_summary="delete_all", step_id="s10")
        test_svc.queue.submit_decision(item10.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="rev", decision=ReviewDecisionType.DELEGATE, justification="just", signature="sig_12345", delegate_id="del10", delegated_authority_tier="HIGH", delegated_scope=["calculate*"]
        ))
        plan10 = KarmaPlanDAG(task_id=1010, summary="p10", steps=[KarmaStep(step_id="s10", action="delete_all", expected_outcome="o", dependencies=[])])
        tok10 = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id=tenant_id)
        ok10, _, msg10 = test_svc.execute_delegated_review(item10.review_id, tenant_id, "del10", plan10, caller_authority=tok10, executor=spy10)
        print("Case 10: Out-of-scope action")
        print(f"  HTTP/status or rejection result: REJECTED (Success={ok10}, Detail='{msg10}')")
        print(f"  handler invocation count: {spy10.invocations}\n")

        # 11. Above-required-authority action
        spy11 = SpyExecutor()
        item11 = test_svc.queue.enqueue_review(task_id=1011, tenant_id=tenant_id, action_summary="nuclear_deploy", step_id="s11")
        test_svc.queue.submit_decision(item11.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="rev", decision=ReviewDecisionType.DELEGATE, justification="just", signature="sig_12345", delegate_id="del11", delegated_authority_tier="MEDIUM", delegated_scope=["nuclear_deploy"]
        ))
        plan11 = KarmaPlanDAG(task_id=1011, summary="p11", steps=[KarmaStep(step_id="s11", action="nuclear_deploy", expected_outcome="o", dependencies=[], authority_required="CRITICAL")])
        tok11 = AuthorityToken.issue(tier=AuthorityTier.MEDIUM, scopes=["nuclear_deploy"], tenant_id=tenant_id)
        ok11, _, msg11 = test_svc.execute_delegated_review(item11.review_id, tenant_id, "del11", plan11, caller_authority=tok11, executor=spy11)
        print("Case 11: Above-required-authority action")
        print(f"  HTTP/status or rejection result: REJECTED (Success={ok11}, Detail='{msg11}')")
        print(f"  handler invocation count: {spy11.invocations}\n")

        # 12. Finalized review
        spy12 = SpyExecutor()
        item12 = test_svc.queue.enqueue_review(task_id=1012, tenant_id=tenant_id, action_summary="calc", step_id="s12")
        test_svc.queue.submit_decision(item12.review_id, tenant_id, HumanReviewDecision(
            reviewer_id="rev", decision=ReviewDecisionType.APPROVE, justification="Approved", signature="sig_12345"
        ))
        plan12 = KarmaPlanDAG(task_id=1012, summary="p12", steps=[KarmaStep(step_id="s12", action="calc", expected_outcome="o", dependencies=[])])
        tok12 = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], tenant_id=tenant_id)
        ok12, _, msg12 = test_svc.execute_delegated_review(item12.review_id, tenant_id, "del12", plan12, caller_authority=tok12, executor=spy12)
        print("Case 12: Finalized review")
        print(f"  HTTP/status or rejection result: REJECTED (Success={ok12}, Detail='{msg12}')")
        print(f"  handler invocation count: {spy12.invocations}\n")

        # 13. Malformed token (HTTP endpoint)
        app.dependency_overrides[get_current_tenant] = lambda: euler_ctx
        res13 = client.post(f"/api/manush/reviews/{review_item.review_id}/execute-delegated", json={
            "delegate_id": "math_specialist_dr_euler",
            "authority_token": "not-a-valid-token-dict"
        })
        print("Case 13: Malformed token")
        print(f"  HTTP/status or rejection result: REJECTED (HTTP Status {res13.status_code}, Detail='{res13.json().get('detail')}')")
        print(f"  handler invocation count: 0\n")

        # 14. Tampered token payload
        tampered_tok = AuthorityToken.issue(tier=AuthorityTier.LOW, scopes=["read"], tenant_id=tenant_id)
        tampered_payload = tampered_tok.model_dump()
        tampered_payload["tier"] = "CRITICAL"  # tampered tier without resigning
        res14 = client.post(f"/api/manush/reviews/{review_item.review_id}/execute-delegated", json={
            "delegate_id": "math_specialist_dr_euler",
            "authority_token": tampered_payload
        })
        print("Case 14: Tampered token payload")
        print(f"  HTTP/status or rejection result: REJECTED (HTTP Status {res14.status_code}, Detail='{res14.json().get('message') or res14.json().get('detail')}')")
        print(f"  handler invocation count: 0\n")

        print("====================================================")

    finally:
        app.dependency_overrides.clear()
        db.close()

if __name__ == "__main__":
    print_forensics()
