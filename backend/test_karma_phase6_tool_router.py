"""
KARMA Phase 6 Test Suite: Tool Router & Trust Registry
Strictly tests Whitesheet §7.4 & Appendix F (SP-6) compliance.
Includes deep security audits for authority spoofing, tie-breaking, and fail-closed behaviors.
"""
import pytest
import concurrent.futures
from pydantic import ValidationError

from app.core.karma.tool_registry import (
    KarmaToolDefinition,
    KarmaToolRegistry,
    get_default_tool_registry
)
from app.core.karma.tool_router import (
    KarmaToolRouter,
    KarmaRoutingDecision
)
from app.core.karma.plan_dag import KarmaStep


def test_tool_registration():
    reg = KarmaToolRegistry()
    tool = KarmaToolDefinition(
        tool_id="test_calc",
        name="Test Calculator",
        capabilities=["calculate", "math"],
        trust_score=0.95,
        cost=0.1,
        authority_required="LOW"
    )
    reg.register_tool(tool)
    assert len(reg.list_tools()) == 1
    assert reg.get_tool("test_calc") == tool


def test_malformed_tool_rejection():
    with pytest.raises(ValidationError):
        # Empty capabilities
        KarmaToolDefinition(
            tool_id="bad_tool",
            name="Bad Tool",
            capabilities=[]
        )

    with pytest.raises(ValidationError):
        # Invalid trust score (> 1.0)
        KarmaToolDefinition(
            tool_id="bad_trust",
            name="Bad Trust",
            capabilities=["math"],
            trust_score=1.5
        )


def test_single_eligible_tool_selection():
    reg = get_default_tool_registry()
    router = KarmaToolRouter(reg)

    decision = router.route(action="calculate 15 * 4", caller_authority="LOW")
    assert decision.status == "ROUTED"
    assert decision.selected_tool_id == "calculator"
    assert decision.routing_score > 0.0
    assert "calculator" in decision.fallback_chain


def test_multiple_eligible_tools_ranking_and_fallback():
    reg = KarmaToolRegistry()
    # Register 3 tools that can all do "math" with varying trust and cost
    t1 = KarmaToolDefinition(tool_id="t_slow_trusted", name="Slow Trusted", capabilities=["math"], trust_score=0.99, cost=2.0)
    t2 = KarmaToolDefinition(tool_id="t_fast_trusted", name="Fast Trusted", capabilities=["math"], trust_score=0.99, cost=0.01)
    t3 = KarmaToolDefinition(tool_id="t_low_trust", name="Low Trust", capabilities=["math"], trust_score=0.50, cost=0.01)

    reg.register_tool(t1)
    reg.register_tool(t2)
    reg.register_tool(t3)

    router = KarmaToolRouter(reg)
    decision = router.route(action="math", caller_authority="LOW")

    assert decision.status == "ROUTED"
    assert decision.selected_tool_id == "t_fast_trusted"  # Higher score due to low cost
    assert decision.fallback_chain[0] == "t_fast_trusted"


def test_trust_score_influence():
    reg = KarmaToolRegistry()
    t_high_trust = KarmaToolDefinition(tool_id="t_high", name="High", capabilities=["search"], trust_score=0.99, cost=0.1)
    t_low_trust = KarmaToolDefinition(tool_id="t_low", name="Low", capabilities=["search"], trust_score=0.40, cost=0.1)

    reg.register_tool(t_high_trust)
    reg.register_tool(t_low_trust)

    router = KarmaToolRouter(reg)
    decision = router.route(action="search", caller_authority="LOW")
    assert decision.selected_tool_id == "t_high"

    # Now degrade trust score of t_high
    reg.update_trust_score("t_high", 0.20)
    decision2 = router.route(action="search", caller_authority="LOW")
    assert decision2.selected_tool_id == "t_low"


def test_unavailable_tool_rejection():
    reg = get_default_tool_registry()
    reg.set_availability("calculator", False)

    router = KarmaToolRouter(reg)
    decision = router.route(action="calculate", caller_authority="LOW")
    assert decision.status == "UNAVAILABLE"
    assert decision.selected_tool_id is None


def test_capability_mismatch_rejection():
    reg = get_default_tool_registry()
    router = KarmaToolRouter(reg)

    decision = router.route(action="quantum_teleportation_flux", caller_authority="LOW")
    assert decision.status == "NO_CAPABLE_TOOL"
    assert decision.selected_tool_id is None


def test_insufficient_authority_rejection():
    reg = get_default_tool_registry()
    router = KarmaToolRouter(reg)

    # Financial settlement requires HIGH authority
    decision = router.route(action="settlement", caller_authority="LOW")
    assert decision.status == "INSUFFICIENT_AUTHORITY"
    assert decision.selected_tool_id is None

    # Elevated authority caller is approved
    decision_auth = router.route(action="settlement", caller_authority="HIGH")
    assert decision_auth.status == "ROUTED"
    assert decision_auth.selected_tool_id == "financial_settlement_api"


def test_constitutional_compliance_veto():
    reg = get_default_tool_registry()
    # Unconstitutional tool
    bad_tool = KarmaToolDefinition(
        tool_id="unconstitutional_sniffer",
        name="Privacy Violating Sniffer",
        capabilities=["network_sniff"],
        constitutional_compliant=False,
        authority_required="LOW"
    )
    reg.register_tool(bad_tool)

    router = KarmaToolRouter(reg)
    decision = router.route(action="network_sniff", caller_authority="CRITICAL")
    assert decision.status == "CONSTITUTIONAL_VIOLATION"
    assert decision.selected_tool_id is None


def test_deterministic_routing():
    reg = get_default_tool_registry()
    router = KarmaToolRouter(reg)

    decisions = [router.route("calculate 100 / 5", "LOW") for _ in range(50)]
    first = decisions[0]
    for d in decisions:
        assert d.selected_tool_id == first.selected_tool_id
        assert d.routing_score == first.routing_score
        assert d.fallback_chain == first.fallback_chain


def test_phase5_karma_step_integration():
    reg = get_default_tool_registry()
    router = KarmaToolRouter(reg)

    step = KarmaStep(
        step_id="step_1",
        action="calculate monthly compound interest",
        tool="calculator",
        reason="Required for projection",
        expected_outcome="Interest calculated",
        authority_required="LOW"
    )

    decision = router.route_step(step, caller_authority="LOW")
    assert decision.status == "ROUTED"
    assert decision.selected_tool_id == "calculator"


def test_missing_authority_context_fails_closed():
    reg = get_default_tool_registry()
    router = KarmaToolRouter(reg)

    # Calling with None or empty string must default to LOW and fail closed on HIGH tools
    decision_none = router.route(action="wire_transfer", caller_authority=None)
    assert decision_none.status == "INSUFFICIENT_AUTHORITY"
    assert decision_none.selected_tool_id is None

    decision_empty = router.route(action="wire_transfer", caller_authority="")
    assert decision_empty.status == "INSUFFICIENT_AUTHORITY"
    assert decision_empty.selected_tool_id is None


def test_forged_authority_in_step_cannot_bypass_registered_tool_gate():
    reg = get_default_tool_registry()
    router = KarmaToolRouter(reg)

    # Malicious client crafts a Step claiming authority_required="LOW" for a high-risk financial settlement
    malicious_step = KarmaStep(
        step_id="step_hack",
        action="wire_transfer to foreign bank",
        tool="financial_settlement_api",
        reason="Attacker claim",
        expected_outcome="Transferred",
        authority_required="LOW"  # Client claims LOW
    )

    # Server router validates against caller's actual verified authority ("LOW") against registered tool requirement ("HIGH")
    decision = router.route_step(malicious_step, caller_authority="LOW")
    assert decision.status == "INSUFFICIENT_AUTHORITY"
    assert decision.selected_tool_id is None
    assert "requires authority tier 'HIGH'" in decision.rationale


def test_malformed_invalid_authority_tier():
    reg = get_default_tool_registry()
    router = KarmaToolRouter(reg)

    # Unrecognized authority string (e.g. "SUPERADMIN_ROOT_BYPASS") defaults safely to LOW tier
    decision = router.route(action="settlement", caller_authority="SUPERADMIN_ROOT_BYPASS")
    assert decision.status == "INSUFFICIENT_AUTHORITY"
    assert decision.selected_tool_id is None


def test_deterministic_ranking_on_exact_tie():
    reg = KarmaToolRegistry()
    # 2 tools with identical capability, trust, cost, and authority
    tool_b = KarmaToolDefinition(tool_id="tool_beta", name="Beta", capabilities=["compress"], trust_score=0.90, cost=0.05)
    tool_a = KarmaToolDefinition(tool_id="tool_alpha", name="Alpha", capabilities=["compress"], trust_score=0.90, cost=0.05)

    reg.register_tool(tool_b)
    reg.register_tool(tool_a)

    router = KarmaToolRouter(reg)
    # Must tie-break deterministically using alphabetical tool_id (tool_alpha wins)
    decision = router.route(action="compress", caller_authority="LOW")
    assert decision.selected_tool_id == "tool_alpha"
    assert decision.fallback_chain == ["tool_alpha", "tool_beta"]


def test_non_execution_guarantee():
    reg = get_default_tool_registry()
    router = KarmaToolRouter(reg)

    # Route an action; confirm it is purely an auditable data model with 0 side effects
    decision = router.route(action="calculate 1 + 1", caller_authority="LOW")
    assert isinstance(decision, KarmaRoutingDecision)
    assert not hasattr(decision, "output")  # No execution output field


def test_concurrent_routing():
    reg = get_default_tool_registry()
    router = KarmaToolRouter(reg)

    def route_worker(idx: int):
        if idx % 2 == 0:
            return router.route("calculate 10 * 10", "LOW")
        else:
            return router.route("calendar_lookup 2026", "LOW")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(route_worker, i) for i in range(40)]
        results = [f.result() for f in futures]

    assert len(results) == 40
    assert all(r.status == "ROUTED" for r in results)


def run_all_phase6_tests():
    print("==================================================")
    print("KARMA PHASE 6: TOOL ROUTER & TRUST REGISTRY TEST SUITE")
    print("==================================================")

    test_tool_registration()
    print("  [PASS] Tool registration & lookup.")

    test_malformed_tool_rejection()
    print("  [PASS] Malformed tool definition rejected.")

    test_single_eligible_tool_selection()
    print("  [PASS] Single eligible tool selection.")

    test_multiple_eligible_tools_ranking_and_fallback()
    print("  [PASS] Multiple eligible tools ranking & fallback chain.")

    test_trust_score_influence()
    print("  [PASS] Dynamic trust score adjustment & routing influence.")

    test_unavailable_tool_rejection()
    print("  [PASS] Unavailable tool rejection.")

    test_capability_mismatch_rejection()
    print("  [PASS] Capability mismatch rejection.")

    test_insufficient_authority_rejection()
    print("  [PASS] Insufficient authority rejection (Fail-Closed).")

    test_missing_authority_context_fails_closed()
    print("  [PASS] Missing/empty authority context fails closed to lowest tier.")

    test_forged_authority_in_step_cannot_bypass_registered_tool_gate()
    print("  [PASS] Forged Step authority cannot bypass registered tool gate.")

    test_malformed_invalid_authority_tier()
    print("  [PASS] Unrecognized authority strings default safely to lowest tier.")

    test_deterministic_ranking_on_exact_tie()
    print("  [PASS] Deterministic alphabetical tie-breaking on identical scores.")

    test_constitutional_compliance_veto()
    print("  [PASS] Constitutional governance constraint enforcement.")

    test_deterministic_routing()
    print("  [PASS] 50 consecutive deterministic routing queries.")

    test_phase5_karma_step_integration()
    print("  [PASS] Phase 5 KarmaStep -> router integration.")

    test_non_execution_guarantee()
    print("  [PASS] Router non-execution guarantee (pure decision).")

    test_concurrent_routing()
    print("  [PASS] 40 concurrent multi-thread routing queries.")

    print("\n==================================================")
    print("ALL 17 KARMA PHASE 6 TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_phase6_tests()
