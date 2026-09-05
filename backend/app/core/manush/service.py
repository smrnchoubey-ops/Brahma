"""
MANUSH Human Oversight Service & CHITRA Audit Integration
Strictly conforms to BRAHMA COS Whitesheet §12.0 & §12.5.

Coordinates review item lifecycle, dual-authorization checks, and appends
canonical CHITRA audit records (faculty="MANUSH", event_type="human_review").
"""
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy.orm import Session

from app.core.manush.decision import ReviewItem, ReviewStatus, HumanReviewDecision, ReviewDecisionType
from app.core.manush.review_queue import ManushReviewQueue
from app.repositories.chitra_repository import chitra_repository


class ManushOversightService:
    """
    High-level MANUSH Human Oversight & Escalation Service.
    """
    def __init__(self, queue: Optional[ManushReviewQueue] = None):
        self.queue = queue or ManushReviewQueue()

    def escalate_for_review(
        self,
        task_id: int,
        tenant_id: str,
        action_summary: str,
        step_id: Optional[str] = None,
        risk_tier: str = "HIGH",
        requires_dual_auth: bool = False,
        ttl_seconds: Optional[int] = None,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ReviewItem:
        """
        Escalates a task or step to the human review queue and records CHITRA audit event.
        """
        item = self.queue.enqueue_review(
            task_id=task_id,
            tenant_id=tenant_id,
            action_summary=action_summary,
            step_id=step_id,
            risk_tier=risk_tier,
            requires_dual_auth=requires_dual_auth,
            ttl_seconds=ttl_seconds,
            metadata=metadata
        )

        if db_session and task_id:
            try:
                chitra_evt = chitra_repository.append_event(
                    db=db_session,
                    task_id=task_id,
                    faculty="MANUSH",
                    event_type="human_review",
                    decision={
                        "review_id": item.review_id,
                        "action_summary": action_summary,
                        "step_id": step_id,
                        "risk_tier": risk_tier,
                        "requires_dual_auth": requires_dual_auth,
                        "status": item.status.value,
                        "tenant_id": tenant_id
                    },
                    confidence=1.0,
                    outcome="ESCALATED_FOR_HUMAN_REVIEW",
                    session_id=session_id or f"ses_manush_{task_id}",
                    user_id=user_id
                )
                item.chitra_event_id = chitra_evt.event_id
            except Exception:
                pass

        return item

    def resolve_review(
        self,
        review_id: str,
        tenant_id: str,
        decision: HumanReviewDecision,
        plan: Optional[Any] = None,
        caller_authority: Optional[Any] = None,
        executor: Optional[Any] = None,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> Tuple[bool, ReviewItem, str]:
        """
        Submits human review verdict, records final CHITRA audit event, and automatically
        resumes amended execution through MARYADA + KARMA if plan is provided (§12.1, CA-006).
        """
        success, item, msg = self.queue.submit_decision(
            review_id=review_id,
            tenant_id=tenant_id,
            decision=decision
        )

        if success and db_session and item and item.task_id:
            try:
                dec_payload: Dict[str, Any] = {
                    "review_id": review_id,
                    "reviewer_id": decision.reviewer_id,
                    "decision": decision.decision.value,
                    "justification": decision.justification,
                    "status": item.status.value,
                    "final_justification": item.final_justification
                }
                if item.status == ReviewStatus.AMENDED_BY_HUMAN:
                    dec_payload["original_action"] = item.original_action
                    dec_payload["amended_action"] = item.amended_action
                    dec_payload["amended_parameters"] = item.amended_parameters

                if item.status == ReviewStatus.DELEGATED_BY_HUMAN:
                    dec_payload["delegate_id"] = item.delegate_id
                    dec_payload["delegated_scope"] = item.delegated_scope
                    dec_payload["delegated_authority_tier"] = item.delegated_authority_tier
                    dec_payload["delegation_expiry"] = item.delegation_expiry

                if item.status == ReviewStatus.TERMINATED_BY_HUMAN:
                    from app.models.task import Task
                    t = db_session.query(Task).filter(Task.id == item.task_id).first()
                    if not t:
                        db_session.rollback()
                        if item.terminations and item.terminations[-1] == decision:
                            item.terminations.pop()
                        item.status = ReviewStatus.PENDING_REVIEW
                        item.final_justification = None
                        return False, item, f"Database error: Task {item.task_id} not found in database to terminate."
                    t.status = "TERMINATED"
                    db_session.commit()

                chitra_repository.append_event(
                    db=db_session,
                    task_id=item.task_id,
                    faculty="MANUSH",
                    event_type="human_review",
                    decision=dec_payload,
                    confidence=1.0 if item.status in [ReviewStatus.APPROVED_BY_HUMAN, ReviewStatus.AMENDED_BY_HUMAN, ReviewStatus.TERMINATED_BY_HUMAN, ReviewStatus.DELEGATED_BY_HUMAN] else 0.0,
                    outcome=item.status.value,
                    session_id=session_id or f"ses_manush_{item.task_id}",
                    user_id=user_id
                )
            except Exception as e:
                db_session.rollback()
                if item.status == ReviewStatus.TERMINATED_BY_HUMAN:
                    if item.terminations and item.terminations[-1] == decision:
                        item.terminations.pop()
                    item.status = ReviewStatus.PENDING_REVIEW
                    item.final_justification = None
                    return False, item, f"Database persistence error during termination: {str(e)}"
                if item.status == ReviewStatus.DELEGATED_BY_HUMAN:
                    if item.delegations and item.delegations[-1] == decision:
                        item.delegations.pop()
                    item.status = ReviewStatus.PENDING_REVIEW
                    item.delegate_id = None
                    item.delegated_scope = None
                    item.delegated_authority_tier = None
                    item.delegation_expiry = None
                    item.final_justification = None
                    return False, item, f"Database persistence error during delegation: {str(e)}"
                return False, item, f"Database persistence error: {str(e)}"

        # Production AMEND Resume Integration (§12.1, CA-006)
        if success and item.status == ReviewStatus.AMENDED_BY_HUMAN and plan is not None:
            res_ok, exec_rep, res_msg = self.resume_amended_execution(
                review_id=review_id,
                tenant_id=tenant_id,
                plan=plan,
                caller_authority=caller_authority,
                executor=executor,
                db_session=db_session,
                user_id=user_id
            )
            if not res_ok:
                return False, item, f"Review amended but execution resume blocked: {res_msg}"
            return True, item, f"Review amended and execution resumed: {res_msg}"

        return success, item, msg


    def re_evaluate_amended_action(
        self,
        item: ReviewItem,
        caller_authority: Optional[Any] = None,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None
    ) -> Any:
        """
        Re-evaluates an amended action against MARYADA constitutional governance
        and authority checks prior to execution (Whitesheet Appendix A CA-006).
        """
        from app.core.maryada.gatekeeper import MaryadaGatekeeper
        action_to_eval = item.amended_action or item.action_summary
        return MaryadaGatekeeper.evaluate_action_gate(
            action=action_to_eval,
            caller_authority=caller_authority,
            tenant_id=item.tenant_id,
            db_session=db_session,
            task_id=item.task_id,
            user_id=user_id
        )

    def _sync_task_execution_result(
        self,
        task_id: int,
        exec_report: Any,
        db_session: Optional[Session],
        user_id: Optional[int] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Synchronizes the KARMA execution report, results, and lifecycle status into the PostgreSQL Task record.
        Fails closed on missing database session, missing/invalid task_id, malformed report,
        unsupported report status, or database persistence failure.
        """
        if db_session is None:
            return False, "Database persistence error: Missing database session (fail-closed)."

        if not task_id or not isinstance(task_id, int) or task_id <= 0:
            return False, "Database persistence error: Missing or invalid task_id (fail-closed)."

        if exec_report is None:
            return False, "Database persistence error: Missing execution report (fail-closed)."

        try:
            from app.models.task import Task
            query = db_session.query(Task).filter(Task.id == task_id)
            if user_id is not None:
                query = query.filter(Task.user_id == user_id)
            task = query.first()

            if not task:
                db_session.rollback()
                return False, f"Database persistence error: Task {task_id} not found."

            report_dict = exec_report.model_dump() if hasattr(exec_report, "model_dump") else (exec_report if isinstance(exec_report, dict) else {})
            raw_status = getattr(exec_report, "status", None) or report_dict.get("status") or report_dict.get("execution_status")

            if not raw_status or not isinstance(raw_status, str):
                db_session.rollback()
                return False, "Database persistence error: Execution report missing status (fail-closed)."

            norm_status = raw_status.strip().upper()

            # Extract step output
            extracted_output = None
            if hasattr(exec_report, "step_results") and exec_report.step_results:
                for sr in exec_report.step_results.values():
                    if getattr(sr, "output", None) is not None:
                        extracted_output = sr.output
                        break
            elif isinstance(report_dict.get("step_results"), dict):
                for sr in report_dict["step_results"].values():
                    if isinstance(sr, dict) and sr.get("output") is not None:
                        extracted_output = sr["output"]
                        break

            if extracted_output is None:
                if "result" in report_dict:
                    extracted_output = report_dict["result"]
                elif "results" in report_dict:
                    extracted_output = report_dict["results"]

            if isinstance(extracted_output, dict) and "result" in extracted_output:
                res_val = extracted_output["result"]
            else:
                res_val = extracted_output

            # Strict lifecycle status mapping & validation
            if norm_status in ["COMPLETED", "SUCCESS", "EXECUTED"]:
                task_status = "COMPLETED"
                result_status = "EXECUTED"
            elif norm_status in ["FAILED", "FAILURE", "ERROR"]:
                task_status = "FAILED"
                result_status = "FAILED"
            elif norm_status in ["BLOCKED", "ESCALATED"]:
                task_status = norm_status
                result_status = norm_status
            else:
                db_session.rollback()
                return False, f"Database persistence error: Unsupported execution report status '{raw_status}' (fail-closed)."

            # Ensure malformed/missing execution results cannot be reported as successful durable completion
            if task_status == "COMPLETED" and res_val is None and not extracted_output and not report_dict.get("step_results") and not report_dict.get("results"):
                db_session.rollback()
                return False, "Database persistence error: Execution report marked COMPLETED but contains no execution output/result (fail-closed)."

            result_payload = {
                "status": result_status,
                "result": res_val,
                "output": extracted_output,
                "report": report_dict
            }

            task.execution_result = result_payload
            task.status = task_status

            db_session.commit()
            return True, None
        except Exception as e:
            if db_session:
                try:
                    db_session.rollback()
                except Exception:
                    pass
            return False, f"Database persistence error during task update: {str(e)}"

    def resume_amended_execution(
        self,
        review_id: str,
        tenant_id: str,
        plan: Any,
        caller_authority: Optional[Any] = None,
        executor: Optional[Any] = None,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None
    ) -> Tuple[bool, Any, str]:
        """
        Production execution resume path for AMENDED_BY_HUMAN review items (§12.1, CA-006, §7.2).
        1. Validates review item is AMENDED_BY_HUMAN for tenant_id.
        2. Mandatorily invokes re_evaluate_amended_action() to verify MARYADA governance.
        3. If MARYADA rejects/blocks -> aborts fail-closed, does NOT mutate step or invoke tool.
        4. If MARYADA approves -> updates target step (action + parameters), dispatches through existing KARMA executor.
        5. Synchronizes execution result and completed lifecycle status to PostgreSQL Task.
        """
        item = self.queue.get_item(review_id=review_id, tenant_id=tenant_id)
        if not item or (item.tenant_id != tenant_id and tenant_id != "global"):
            return False, None, f"Review item '{review_id}' not found for tenant."

        if item.status != ReviewStatus.AMENDED_BY_HUMAN:
            return False, None, f"Review item '{review_id}' is not in AMENDED_BY_HUMAN status (current: {item.status.value})."

        # Mandatory MARYADA Re-Evaluation Gate (CA-006)
        verdict = self.re_evaluate_amended_action(
            item=item,
            caller_authority=caller_authority,
            db_session=db_session,
            user_id=user_id
        )

        if not getattr(verdict, "approved", False):
            justification = getattr(verdict, "justification", "Rejected by MARYADA governance")
            return False, verdict, f"Amended action rejected by MARYADA governance: {justification}"

        # Locate and update target step in KarmaPlanDAG
        target_step = None
        if hasattr(plan, "steps") and plan.steps:
            if item.step_id:
                target_step = next((s for s in plan.steps if s.step_id == item.step_id), None)
            if not target_step and item.original_action:
                target_step = next((s for s in plan.steps if s.action == item.original_action), None)
            if not target_step and len(plan.steps) == 1:
                target_step = plan.steps[0]

        if not target_step:
            return False, verdict, f"Target step '{item.step_id}' not found in plan DAG."

        # Inject amended action and parameters into the target step
        target_step.action = item.amended_action or target_step.action
        if item.amended_parameters:
            if isinstance(item.amended_parameters, dict) and "expected_outcome" in item.amended_parameters:
                target_step.expected_outcome = str(item.amended_parameters["expected_outcome"])
            if hasattr(target_step, "parameters"):
                target_step.parameters = item.amended_parameters
            elif hasattr(target_step, "model_extra") and target_step.model_extra is not None:
                target_step.model_extra["parameters"] = item.amended_parameters
            elif hasattr(target_step, "__dict__"):
                target_step.__dict__["parameters"] = item.amended_parameters

        target_step.status = "PENDING"

        # Dispatch via existing KARMA executor (§7.2, §7.4)
        if executor is None:
            from app.core.karma.executor import KarmaDAGExecutor
            executor = KarmaDAGExecutor()

        exec_report = executor.execute_plan(
            plan=plan,
            caller_authority=caller_authority,
            db_session=db_session,
            user_id=user_id
        )

        if db_session is not None:
            sync_ok, sync_err = self._sync_task_execution_result(
                task_id=item.task_id,
                exec_report=exec_report,
                db_session=db_session,
                user_id=user_id
            )
            if not sync_ok:
                return False, exec_report, f"Execution succeeded but PostgreSQL task persistence failed: {sync_err}"

        return True, exec_report, "Amended execution completed successfully."

    def execute_delegated_review(
        self,
        review_id: str,
        tenant_id: str,
        delegate_id: str,
        plan: Any,
        caller_authority: Optional[Any] = None,
        executor: Optional[Any] = None,
        db_session: Optional[Session] = None,
        user_id: Optional[int] = None
    ) -> Tuple[bool, Any, str]:
        """
        Production execution path for authorized delegate execution (§12.1, CA-006, §13.4).
        1. Validates review item is DELEGATED_BY_HUMAN and bounded to tenant.
        2. Validates caller identity matches the authorized delegate_id.
        3. Validates delegation has not expired.
        4. Validates §13.4 AuthorityToken (signature, expiry, tenant, scopes).
        5. Validates caller authority tier does not exceed delegated tier ceiling (HARD FAIL).
        6. Validates target step action is within token scope and delegated_scope.
        7. Re-evaluates action through MARYADA constitutional gatekeeper.
        8. Dispatches execution through existing KARMA executor.
        """
        from app.core.maryada.token import AuthorityToken

        item = self.queue.get_item(review_id=review_id, tenant_id=tenant_id)
        if not item or (item.tenant_id != tenant_id and tenant_id != "global"):
            return False, None, f"Review item '{review_id}' not found for tenant."

        if item.status != ReviewStatus.DELEGATED_BY_HUMAN:
            return False, None, f"Review item '{review_id}' is not in DELEGATED_BY_HUMAN status (current: {item.status.value})."

        # 1. Verify delegate identity
        if not delegate_id or delegate_id.strip() != item.delegate_id:
            return False, None, f"Access Denied: Caller '{delegate_id}' is not the authorized delegate '{item.delegate_id}'."

        # 2. Verify delegation expiry
        if item.delegation_expiry:
            try:
                from datetime import datetime, timezone
                exp_dt = datetime.fromisoformat(item.delegation_expiry)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > exp_dt:
                    return False, None, "Delegation authorization has expired."
            except Exception as e:
                return False, None, f"Invalid delegation expiry format: {e}"

        # 3. Locate target step in plan
        target_step = None
        if hasattr(plan, "steps") and plan.steps:
            if item.step_id:
                target_step = next((s for s in plan.steps if s.step_id == item.step_id), None)
            if not target_step and item.original_action:
                target_step = next((s for s in plan.steps if s.action == item.original_action), None)
            if not target_step and len(plan.steps) == 1:
                target_step = plan.steps[0]

        if not target_step:
            return False, None, f"Target step '{item.step_id}' not found in plan DAG."

        step_action = target_step.action

        # 4. Mandatory §13.4 AuthorityToken validation (No unsigned LOW fallback)
        auth_token: Optional[AuthorityToken] = None
        if caller_authority is None:
            return False, None, "Missing mandatory §13.4 AuthorityToken for delegated execution (fail-closed)."
        elif isinstance(caller_authority, AuthorityToken):
            auth_token = caller_authority
        elif isinstance(caller_authority, dict):
            try:
                auth_token = AuthorityToken(**caller_authority)
            except Exception as e:
                return False, None, f"Invalid AuthorityToken structure: {e}"
        elif isinstance(caller_authority, str):
            try:
                auth_token = AuthorityToken.decode(caller_authority)
            except Exception:
                # String tier name fallback only if explicitly passing mock tier in unit test with signature
                return False, None, "String authority must be a valid encoded §13.4 AuthorityToken."
        else:
            return False, None, f"Unsupported caller_authority type: {type(caller_authority)}"

        # Cryptographic signature validation
        if not auth_token.verify_signature():
            return False, None, "AuthorityToken cryptographic signature verification failed (fail-closed)."

        # Expiry & not-yet-valid validation
        if auth_token.is_expired():
            return False, None, "AuthorityToken has expired (fail-closed)."
        if auth_token.is_not_yet_valid():
            return False, None, "AuthorityToken is not yet valid (fail-closed)."

        # Tenant binding validation
        if auth_token.tenant_id != tenant_id and auth_token.tenant_id != "global":
            return False, None, f"AuthorityToken tenant mismatch: token bound to '{auth_token.tenant_id}', request is for '{tenant_id}'."

        # 5. Scope boundary checks
        # A. AuthorityToken scope validation
        if not auth_token.is_action_in_scope(step_action):
            return False, None, f"Action '{step_action}' is not within AuthorityToken scope: {auth_token.scopes}"

        # B. Delegated supervisory scope ceiling check
        if item.delegated_scope and "*" not in item.delegated_scope:
            action_matched = False
            act_clean = step_action.strip().lower()
            root_word = act_clean.split()[0] if act_clean.split() else ""
            for scope in item.delegated_scope:
                s_clean = scope.strip().lower()
                if s_clean == "*" or s_clean == act_clean or s_clean == root_word or (s_clean.endswith("*") and act_clean.startswith(s_clean[:-1])):
                    action_matched = True
                    break
            if not action_matched:
                return False, None, f"Action '{step_action}' is not within authorized delegated scope: {item.delegated_scope}"

        # 6. Authority tier ordering & ceiling checks (HARD FAIL - No silent downgrade)
        tier_ranks = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        caller_tier_str = auth_token.tier.value if hasattr(auth_token.tier, "value") else str(auth_token.tier)
        caller_rank = tier_ranks.get(caller_tier_str.upper(), 0)

        step_req_str = getattr(target_step, "authority_required", "LOW") or "LOW"
        step_req_rank = tier_ranks.get(step_req_str.upper() if isinstance(step_req_str, str) else "LOW", 0)

        if item.delegated_authority_tier:
            delegated_ceiling_rank = tier_ranks.get(item.delegated_authority_tier.upper(), 0)
            if caller_rank > delegated_ceiling_rank:
                return False, None, f"Security Violation: Caller authority tier '{caller_tier_str}' exceeds delegated ceiling '{item.delegated_authority_tier}' (fail-closed)."
            if delegated_ceiling_rank < step_req_rank:
                return False, None, f"Security Violation: Delegated authority ceiling '{item.delegated_authority_tier}' is insufficient for step requirement '{step_req_str}' (fail-closed)."

        if caller_rank < step_req_rank:
            return False, None, f"Security Violation: Caller authority tier '{caller_tier_str}' is insufficient for step requirement '{step_req_str}' (fail-closed)."

        # 7. Re-evaluate action against MARYADA gatekeeper
        from app.core.maryada.gatekeeper import MaryadaGatekeeper
        verdict = MaryadaGatekeeper.evaluate_action_gate(
            action=step_action,
            caller_authority=auth_token,
            tenant_id=tenant_id,
            db_session=db_session,
            task_id=item.task_id,
            user_id=user_id
        )

        if not getattr(verdict, "approved", False):
            justification = getattr(verdict, "justification", "Rejected by MARYADA governance")
            return False, verdict, f"Delegated action rejected by MARYADA governance: {justification}"

        target_step.status = "PENDING"

        # 8. Dispatch via existing KARMA executor
        if executor is None:
            from app.core.karma.executor import KarmaDAGExecutor
            executor = KarmaDAGExecutor()

        exec_report = executor.execute_plan(
            plan=plan,
            caller_authority=auth_token,
            db_session=db_session,
            user_id=user_id
        )

        if db_session is not None:
            sync_ok, sync_err = self._sync_task_execution_result(
                task_id=item.task_id,
                exec_report=exec_report,
                db_session=db_session,
                user_id=user_id
            )
            if not sync_ok:
                return False, exec_report, f"Execution succeeded but PostgreSQL task persistence failed: {sync_err}"

        return True, exec_report, f"Plan DAG execution successfully completed by authorized delegate '{delegate_id}'."



manush_service = ManushOversightService()



