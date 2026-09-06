"""
MARYADA Phase 2 — §13.4 Cryptographically Signed, Time-Bounded Authority Token Test Suite
Tests conformance to BRAHMA COS Whitesheet §13.0, §13.4, §10.1, and §7.4.

Verifies:
A. Valid signed token + valid scope + valid tenant + sufficient tier -> privileged execution allowed.
B. Missing token -> blocked before tool invocation (fail-closed).
C. Plain "HIGH" / "CRITICAL" string -> blocked for privileged execution.
D. Tampered token -> blocked.
E. Invalid signature -> blocked.
F. Expired token -> blocked.
G. Not-yet-valid token -> blocked.
H. Insufficient tier -> blocked.
I. Unauthorized scope -> blocked.
J. Tenant mismatch -> blocked.
K. Deterministic scope matching (no word-containment leaks).
L. Tool Router & Execution layer integration (privileged tool routing fails without valid token).
"""
import pytest
from datetime import datetime, timezone, timedelta

from app.core.maryada.verdict import AuthorityTier, RiskTier, GateStatus
from app.core.maryada.token import AuthorityToken, get_authority_signing_key
from app.core.maryada.authority_matrix import MaryadaAuthorityMatrix
from app.core.maryada.gatekeeper import MaryadaGatekeeper
from app.core.karma.tool_registry import KarmaToolRegistry, KarmaToolDefinition
from app.core.karma.tool_router import KarmaToolRouter
from app.core.karma.plan_dag import KarmaStep


def test_a_valid_signed_token_allows_privileged_execution():
    """Requirement A: Valid signed token + valid scope + valid tenant + sufficient tier -> allowed."""
    tok = AuthorityToken.issue(
        tier=AuthorityTier.HIGH,
        scopes=["wire_transfer*"],
        ttl_seconds=3600,
        signer_id="TEST_SIGNER_01",
        tenant_id="tenant_alice"
    )
    verdict = MaryadaGatekeeper.evaluate_privileged_action_gate(
        action="wire_transfer 50000 USD",
        authority_token=tok,
        tenant_id="tenant_alice"
    )
    assert verdict.approved is True
    assert verdict.status == GateStatus.APPROVED
    assert verdict.authority_required == AuthorityTier.HIGH
    assert f"HIGH:{tok.token_id}" in (verdict.caller_authority or "")


def test_b_missing_token_blocked():
    """Requirement B: Missing token fails closed before tool invocation."""
    verdict = MaryadaGatekeeper.evaluate_privileged_action_gate(
        action="wire_transfer 50000 USD",
        authority_token=None,
        tenant_id="tenant_alice"
    )
    assert verdict.approved is False
    assert verdict.status == GateStatus.BLOCKED
    assert "missing" in verdict.justification.lower()


def test_c_plain_string_rejected_for_privileged_execution():
    """Requirement C: Plain 'HIGH' / 'CRITICAL' string is blocked for privileged execution."""
    verdict = MaryadaGatekeeper.evaluate_privileged_action_gate(
        action="wire_transfer 50000 USD",
        authority_token="HIGH",
        tenant_id="tenant_alice"
    )
    assert verdict.approved is False
    assert verdict.status == GateStatus.BLOCKED
    assert "not a valid §13.4 cryptographically signed authority token" in verdict.justification.lower()


def test_d_tampered_token_blocked():
    """Requirement D: Tampered token payload is blocked due to cryptographic signature mismatch."""
    tok = AuthorityToken.issue(
        tier=AuthorityTier.MEDIUM,
        scopes=["update_profile"],
        ttl_seconds=3600,
        tenant_id="tenant_alice"
    )
    # Attacker attempts privilege escalation by mutating tier to HIGH
    tok.tier = AuthorityTier.HIGH

    verdict = MaryadaGatekeeper.evaluate_privileged_action_gate(
        action="wire_transfer 50000 USD",
        authority_token=tok,
        tenant_id="tenant_alice"
    )
    assert verdict.approved is False
    assert verdict.status == GateStatus.BLOCKED
    assert "signature verification failed" in verdict.justification.lower()


def test_e_invalid_signature_blocked():
    """Requirement E: Token with forged signature fails closed."""
    tok = AuthorityToken.issue(
        tier=AuthorityTier.HIGH,
        scopes=["*"],
        ttl_seconds=3600,
        tenant_id="tenant_alice"
    )
    tok.signature = "hmac-sha256:deadbeef00112233445566778899aabbccddeeffdeadbeef0011223344556677"

    verdict = MaryadaGatekeeper.evaluate_privileged_action_gate(
        action="wire_transfer 50000 USD",
        authority_token=tok,
        tenant_id="tenant_alice"
    )
    assert verdict.approved is False
    assert verdict.status == GateStatus.BLOCKED
    assert "signature verification failed" in verdict.justification.lower()


def test_f_expired_token_blocked():
    """Requirement F: Expired token fails closed."""
    tok = AuthorityToken.issue(
        tier=AuthorityTier.HIGH,
        scopes=["*"],
        ttl_seconds=-30,  # Expired 30 seconds ago
        tenant_id="tenant_alice"
    )
    verdict = MaryadaGatekeeper.evaluate_privileged_action_gate(
        action="wire_transfer 50000 USD",
        authority_token=tok,
        tenant_id="tenant_alice"
    )
    assert verdict.approved is False
    assert verdict.status == GateStatus.BLOCKED
    assert "expired" in verdict.justification.lower()


def test_g_not_yet_valid_token_blocked():
    """Requirement G: Future-dated token fails closed."""
    future_now = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    future_exp = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    tok = AuthorityToken(
        tier=AuthorityTier.HIGH,
        scopes=["*"],
        issued_at=future_now,
        expires_at=future_exp,
        tenant_id="tenant_alice"
    ).sign()

    verdict = MaryadaGatekeeper.evaluate_privileged_action_gate(
        action="wire_transfer 50000 USD",
        authority_token=tok,
        tenant_id="tenant_alice"
    )
    assert verdict.approved is False
    assert verdict.status == GateStatus.BLOCKED
    assert "not yet valid" in verdict.justification.lower()


def test_h_insufficient_tier_blocked():
    """Requirement H: Valid signed MEDIUM token attempting HIGH action is blocked."""
    tok = AuthorityToken.issue(
        tier=AuthorityTier.MEDIUM,
        scopes=["*"],
        ttl_seconds=3600,
        tenant_id="tenant_alice"
    )
    verdict = MaryadaGatekeeper.evaluate_privileged_action_gate(
        action="wire_transfer 50000 USD",  # Requires HIGH
        authority_token=tok,
        tenant_id="tenant_alice"
    )
    assert verdict.approved is False
    assert verdict.status == GateStatus.BLOCKED
    assert "insufficient authority" in verdict.justification.lower()


def test_i_unauthorized_scope_blocked():
    """Requirement I: Valid signed HIGH token with payroll scope attempting wire_transfer is blocked."""
    tok = AuthorityToken.issue(
        tier=AuthorityTier.HIGH,
        scopes=["payroll_*"],
        ttl_seconds=3600,
        tenant_id="tenant_alice"
    )
    verdict = MaryadaGatekeeper.evaluate_privileged_action_gate(
        action="wire_transfer 50000 USD",
        authority_token=tok,
        tenant_id="tenant_alice"
    )
    assert verdict.approved is False
    assert verdict.status == GateStatus.BLOCKED
    assert "outside authorized token scopes" in verdict.justification.lower()


def test_j_tenant_mismatch_blocked():
    """Requirement J: Token issued for tenant_alice cannot authorize privileged execution for tenant_bob."""
    tok = AuthorityToken.issue(
        tier=AuthorityTier.HIGH,
        scopes=["wire_transfer*"],
        ttl_seconds=3600,
        tenant_id="tenant_alice"
    )
    verdict = MaryadaGatekeeper.evaluate_privileged_action_gate(
        action="wire_transfer 50000 USD",
        authority_token=tok,
        tenant_id="tenant_bob"
    )
    assert verdict.approved is False
    assert verdict.status == GateStatus.BLOCKED
    assert "tenant mismatch" in verdict.justification.lower()


def test_k_deterministic_scope_matching_no_word_containment():
    """Requirement K: Scope 'transfer' must not authorize 'unauthorized_wire_transfer'."""
    tok = AuthorityToken.issue(
        tier=AuthorityTier.HIGH,
        scopes=["transfer"],
        ttl_seconds=3600
    )
    # Exact match works
    assert tok.is_action_in_scope("transfer") is True
    # Word containment without prefix/exact must NOT match
    assert tok.is_action_in_scope("malicious_unauthorized_transfer") is False


def test_l_karma_tool_router_enforces_signed_tokens_on_privileged_tools():
    """Requirement L: Privileged tool routing fails without valid signed token, passes with valid signed token."""
    registry = KarmaToolRegistry()
    registry.register_tool(KarmaToolDefinition(
        tool_id="financial_settlement_tool",
        name="Financial Settlement Tool",
        capabilities=["settlement", "wire_transfer"],
        authority_required="HIGH",
        trust_score=0.99,
        cost=5,
        constitutional_compliant=True,
        is_available=True
    ))

    router = KarmaToolRouter(registry=registry)

    # 1. Plain unsigned string 'HIGH' is rejected when privileged token is required
    decision_plain = router.route(
        action="wire_transfer 50000 USD",
        caller_authority="HIGH",
        tenant_id="tenant_alice",
        require_signed_token=True
    )
    assert decision_plain.status == "INSUFFICIENT_AUTHORITY"
    assert "cryptographically signed authority token" in decision_plain.rationale

    # 2. Wrong tenant token is rejected
    tok_wrong_tenant = AuthorityToken.issue(
        tier=AuthorityTier.HIGH,
        scopes=["wire_transfer*"],
        ttl_seconds=3600,
        tenant_id="tenant_bob"
    )
    decision_wrong_tenant = router.route(
        action="wire_transfer 50000 USD",
        caller_authority=tok_wrong_tenant,
        tenant_id="tenant_alice"
    )
    assert decision_wrong_tenant.status == "INSUFFICIENT_AUTHORITY"
    assert "tenant mismatch" in decision_wrong_tenant.rationale.lower()

    # 3. Valid signed token matching tenant and scope is ROUTED
    tok_valid = AuthorityToken.issue(
        tier=AuthorityTier.HIGH,
        scopes=["wire_transfer*"],
        ttl_seconds=3600,
        tenant_id="tenant_alice"
    )
    decision_valid = router.route(
        action="wire_transfer 50000 USD",
        caller_authority=tok_valid,
        tenant_id="tenant_alice"
    )
    assert decision_valid.status == "ROUTED"
    assert decision_valid.selected_tool_id == "financial_settlement_tool"


def test_m_actual_tool_handler_not_invoked_on_authorization_failure():
    """Requirement 6: Prove actual tool handler is NOT invoked under all negative authorization conditions."""
    from app.core.karma.executor import KarmaDAGExecutor
    from app.core.karma.plan_dag import KarmaPlanDAG

    call_log = []
    def privileged_spy_handler(params):
        call_log.append("INVOKED")
        return {"settled": True}

    executor = KarmaDAGExecutor(custom_handlers={"financial_settlement_api": privileged_spy_handler})

    s1 = KarmaStep(
        step_id="step_settle",
        action="wire_transfer 100000 USD",
        tool="financial_settlement_api",
        expected_outcome="Settled",
        dependencies=[]
    )
    plan = KarmaPlanDAG(task_id=99, summary="Privileged Settle Test", steps=[s1])

    # 1. Invalid signature -> no tool invocation
    bad_sig_tok = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], ttl_seconds=3600, tenant_id="tenant_1")
    bad_sig_tok.signature = "hmac-sha256:0000000000000000000000000000000000000000000000000000000000000000"
    executor.execute_plan(plan, caller_authority=bad_sig_tok, user_id=1)
    assert len(call_log) == 0

    # 2. Expired token -> no tool invocation
    expired_tok = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["*"], ttl_seconds=-60, tenant_id="tenant_1")
    executor.execute_plan(plan, caller_authority=expired_tok, user_id=1)
    assert len(call_log) == 0

    # 3. Bad scope -> no tool invocation
    bad_scope_tok = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["unrelated_scope"], ttl_seconds=3600, tenant_id="tenant_1")
    executor.execute_plan(plan, caller_authority=bad_scope_tok, user_id=1)
    assert len(call_log) == 0

    # 4. Tenant mismatch -> no tool invocation
    wrong_tenant_tok = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["wire_transfer*"], ttl_seconds=3600, tenant_id="tenant_2")
    executor.execute_plan(plan, caller_authority=wrong_tenant_tok, user_id=1)  # user_id 1 -> tenant_1
    assert len(call_log) == 0

    # 5. Valid signed token -> tool IS invoked
    valid_tok = AuthorityToken.issue(tier=AuthorityTier.HIGH, scopes=["wire_transfer*"], ttl_seconds=3600, tenant_id="tenant_1")
    report = executor.execute_plan(plan, caller_authority=valid_tok, user_id=1)
    assert len(call_log) == 1
    assert report.status == "COMPLETED"
