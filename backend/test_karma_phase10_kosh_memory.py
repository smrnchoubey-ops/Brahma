"""
KOSH Phase 10 Comprehensive Test Suite: Multi-Tier Knowledge Core & Episodic Memory
Strictly tests Whitesheet §§9.0–9.7 across 30 explicit scenarios.
Runs against local sandbox database: test_karma_phase10_sandbox.db.
"""
import pytest
import concurrent.futures
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.models.task import Task
from app.models.user import User
from app.models.chitra import ChitraEvent
from app.core.karma.plan_dag import KarmaPlanDAG, KarmaStep
from app.core.karma.executor import KarmaDAGExecutor, KarmaDAGExecutionReport, KarmaStepExecutionResult
from app.core.karma.completion_validator import KarmaCompletionValidator
from app.core.kosh.memory_tiers import MemoryTier, KoshChunk
from app.core.kosh.vector_engine import (
    compute_cosine_similarity,
    generate_deterministic_test_embedding,
    KoshVectorStore
)
from app.core.kosh.episodic_handoff import (
    KoshEpisodicHandoffController,
    KoshEpisodicHandoffResult
)
from app.core.kosh.retrieval_service import (
    KoshRetrievalService,
    KoshRetrievalResult
)
from app.repositories.chitra_repository import chitra_repository
from app.services.chitra_verifier import chitra_verifier

TEST_DB_URL = "sqlite:///./test_karma_phase10_sandbox.db"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine)


def reset_sandbox():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    user_a = User(username="user_alice_p10", hashed_password="pwd")
    user_b = User(username="user_bob_p10", hashed_password="pwd")
    db.add(user_a)
    db.add(user_b)
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)

    task_a = Task(user_id=user_a.id, title="Task A", prompt="Prompt A", status="PENDING")
    task_b = Task(user_id=user_b.id, title="Task B", prompt="Prompt B", status="PENDING")
    db.add(task_a)
    db.add(task_b)
    db.commit()
    db.refresh(task_a)
    db.refresh(task_b)

    u_a, t_a = user_a.id, task_a.id
    u_b, t_b = user_b.id, task_b.id
    db.close()
    return u_a, t_a, u_b, t_b


def fast_mock_sleep(seconds: float):
    pass


# -------------------------------------------------------------
# 1. KNOWLEDGE & VECTOR STORAGE (§9.1, §9.5, §9.6) (1-10)
# -------------------------------------------------------------

def test_1_knowledge_chunk_indexing_and_storage():
    store = KoshVectorStore()
    chunk = KoshChunk(
        chunk_id="chk_01",
        tenant_id="tenant_alice",
        title="Corporate Leave Policy",
        content="Employees receive 24 days annual paid leave.",
        tier=MemoryTier.SEMANTIC_STORE,
        embedding=generate_deterministic_test_embedding("Corporate Leave Policy annual leave")
    )
    store.add_chunk(chunk)
    retrieved = store.get_chunk("chk_01")
    assert retrieved is not None
    assert retrieved.title == "Corporate Leave Policy"


def test_2_768_dim_vector_representation():
    vec = generate_deterministic_test_embedding("Test text for embedding", dim=768)
    assert len(vec) == 768
    # Assert unit vector norm
    import math
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-4


def test_3_cosine_similarity_computation():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    sim = compute_cosine_similarity(v1, v2)
    assert abs(sim - 1.0) < 1e-5


def test_4_orthogonal_and_identical_vectors_similarity():
    v_ident = [0.5, 0.5, 0.5, 0.5]
    v_ortho = [0.5, -0.5, 0.5, -0.5]
    assert abs(compute_cosine_similarity(v_ident, v_ident) - 1.0) < 1e-5
    assert abs(compute_cosine_similarity(v_ident, v_ortho) - 0.0) < 1e-5


def test_5_semantic_similarity_threshold_filtering():
    store = KoshVectorStore()
    store.add_chunk(KoshChunk(
        chunk_id="c_high", tenant_id="tenant_1", title="Math", content="Calculator operations",
        embedding=generate_deterministic_test_embedding("calculate math sum addition")
    ))
    store.add_chunk(KoshChunk(
        chunk_id="c_low", tenant_id="tenant_1", title="Astronomy", content="Deep space telescopes",
        embedding=generate_deterministic_test_embedding("astronomy space galaxy stars")
    ))

    # Query about math with min_similarity 0.70
    query_v = generate_deterministic_test_embedding("calculate math sum")
    results = store.query(query_v, tenant_id="tenant_1", min_similarity=0.70)
    
    assert any(c.chunk_id == "c_high" for c, _ in results)
    assert not any(c.chunk_id == "c_low" for c, _ in results)


def test_6_top_k_ranking_and_truncation():
    store = KoshVectorStore()
    for i in range(10):
        store.add_chunk(KoshChunk(
            chunk_id=f"c_{i}", tenant_id="tenant_1", title=f"Doc {i}", content=f"Content {i} math",
            embedding=generate_deterministic_test_embedding(f"math operation topic {i}")
        ))

    query_v = generate_deterministic_test_embedding("math operation")
    results = store.query(query_v, tenant_id="tenant_1", top_k=3, min_similarity=0.0)
    assert len(results) == 3


def test_7_tier_1_working_context_filtering():
    store = KoshVectorStore()
    store.add_chunk(KoshChunk(
        chunk_id="t1", tenant_id="tenant_1", title="Working Context", content="Active step variables",
        tier=MemoryTier.WORKING_CONTEXT, embedding=generate_deterministic_test_embedding("variables")
    ))
    store.add_chunk(KoshChunk(
        chunk_id="t3", tenant_id="tenant_1", title="Semantic Doc", content="Persistent documentation",
        tier=MemoryTier.SEMANTIC_STORE, embedding=generate_deterministic_test_embedding("variables")
    ))

    q_vec = generate_deterministic_test_embedding("variables")
    results = store.query(q_vec, tenant_id="tenant_1", min_similarity=0.0, tier_filter=[MemoryTier.WORKING_CONTEXT])
    assert len(results) == 1
    assert results[0][0].tier == MemoryTier.WORKING_CONTEXT


def test_8_tier_2_episodic_memory_filtering():
    store = KoshVectorStore()
    store.add_chunk(KoshChunk(
        chunk_id="ep1", tenant_id="tenant_1", title="Episodic Task", content="Executed step trace",
        tier=MemoryTier.EPISODIC, embedding=generate_deterministic_test_embedding("step trace")
    ))
    q_vec = generate_deterministic_test_embedding("step trace")
    results = store.query(q_vec, tenant_id="tenant_1", min_similarity=0.0, tier_filter=[MemoryTier.EPISODIC])
    assert len(results) == 1
    assert results[0][0].tier == MemoryTier.EPISODIC


def test_9_tier_3_semantic_store_filtering():
    store = KoshVectorStore()
    store.add_chunk(KoshChunk(
        chunk_id="s1", tenant_id="tenant_1", title="Policy", content="Security policy",
        tier=MemoryTier.SEMANTIC_STORE, embedding=generate_deterministic_test_embedding("security policy")
    ))
    q_vec = generate_deterministic_test_embedding("security policy")
    results = store.query(q_vec, tenant_id="tenant_1", min_similarity=0.0, tier_filter=[MemoryTier.SEMANTIC_STORE])
    assert len(results) == 1
    assert results[0][0].tier == MemoryTier.SEMANTIC_STORE


def test_10_multi_tier_combined_query():
    store = KoshVectorStore()
    store.add_chunk(KoshChunk(
        chunk_id="t1", tenant_id="tenant_1", title="W", content="A", tier=MemoryTier.WORKING_CONTEXT,
        embedding=generate_deterministic_test_embedding("shared keyword")
    ))
    store.add_chunk(KoshChunk(
        chunk_id="t2", tenant_id="tenant_1", title="E", content="B", tier=MemoryTier.EPISODIC,
        embedding=generate_deterministic_test_embedding("shared keyword")
    ))
    q_vec = generate_deterministic_test_embedding("shared keyword")
    results = store.query(q_vec, tenant_id="tenant_1", min_similarity=0.0, tier_filter=[MemoryTier.WORKING_CONTEXT, MemoryTier.EPISODIC])
    assert len(results) == 2


# -------------------------------------------------------------
# 2. EPISODIC HANDOFF TESTS (§9.3) (11-15)
# -------------------------------------------------------------

def test_11_episodic_handoff_from_completed_plan():
    store = KoshVectorStore()
    step_res = KarmaStepExecutionResult(
        step_id="s1",
        action="calculate 20 + 20",
        status="SUCCEEDED",
        tool_id="calculator",
        output={"result": 40},
        chitra_event_id="evt_01J_CALC",
        verification_status="VERIFIED",
        completion_validation={"is_valid": True, "no_silent_action_valid": True, "audit_trail_ref": "evt_01J_CALC"}
    )
    report = KarmaDAGExecutionReport(
        plan_id="plan_1",
        task_id=101,
        status="COMPLETED",
        total_steps=1,
        succeeded_steps_count=1,
        failed_steps_count=0,
        blocked_steps_count=0,
        step_results={"s1": step_res},
        execution_order=["s1"],
        summary="Plan success"
    )

    handoff = KoshEpisodicHandoffController.process_plan_handoff(report, tenant_id="tenant_alice", vector_store=store)
    assert handoff.success is True
    assert handoff.status == "HANDOFF_INDEXED"
    assert handoff.indexed_chunks_count == 1
    assert len(store._chunks) == 1


def test_12_episodic_handoff_rejected_on_failed_plan():
    store = KoshVectorStore()
    report = KarmaDAGExecutionReport(
        plan_id="plan_fail",
        task_id=102,
        status="FAILED",
        total_steps=1,
        succeeded_steps_count=0,
        failed_steps_count=1,
        blocked_steps_count=0,
        step_results={},
        execution_order=[],
        summary="Failed"
    )
    handoff = KoshEpisodicHandoffController.process_plan_handoff(report, tenant_id="tenant_alice", vector_store=store)
    assert handoff.success is False
    assert handoff.status == "HANDOFF_REJECTED"


def test_13_episodic_handoff_rejected_on_unverified_step():
    store = KoshVectorStore()
    step_res = KarmaStepExecutionResult(
        step_id="s1",
        action="calculate 1+1",
        status="SUCCEEDED",
        output={"result": 2},
        verification_status="FAILED",
        completion_validation={"is_valid": False, "no_silent_action_valid": False}
    )
    report = KarmaDAGExecutionReport(
        plan_id="plan_unverif", task_id=103, status="COMPLETED", total_steps=1,
        succeeded_steps_count=1, failed_steps_count=0, blocked_steps_count=0,
        step_results={"s1": step_res}, execution_order=["s1"], summary="Unverif"
    )
    handoff = KoshEpisodicHandoffController.process_plan_handoff(report, tenant_id="tenant_alice", vector_store=store)
    assert handoff.success is False
    assert handoff.status == "HANDOFF_REJECTED"


def test_14_episodic_handoff_rejected_on_missing_no_silent_action_evidence():
    store = KoshVectorStore()
    step_res = KarmaStepExecutionResult(
        step_id="s1",
        action="calculate 1+1",
        status="SUCCEEDED",
        output={"result": 2},
        verification_status="VERIFIED",
        completion_validation={"is_valid": True, "no_silent_action_valid": False}
    )
    report = KarmaDAGExecutionReport(
        plan_id="plan_no_nsa", task_id=104, status="COMPLETED", total_steps=1,
        succeeded_steps_count=1, failed_steps_count=0, blocked_steps_count=0,
        step_results={"s1": step_res}, execution_order=["s1"], summary="No NSA"
    )
    handoff = KoshEpisodicHandoffController.process_plan_handoff(report, tenant_id="tenant_alice", vector_store=store)
    assert handoff.success is False
    assert handoff.status == "HANDOFF_REJECTED"


def test_15_episodic_handoff_preserves_chitra_audit_references():
    store = KoshVectorStore()
    step_res = KarmaStepExecutionResult(
        step_id="s1",
        action="system_status",
        status="SUCCEEDED",
        tool_id="system_status",
        output={"status": "OPERATIONAL"},
        chitra_event_id="evt_01J_SYS_STAT",
        verification_status="VERIFIED",
        completion_validation={"is_valid": True, "no_silent_action_valid": True, "audit_trail_ref": "evt_01J_SYS_STAT"}
    )
    report = KarmaDAGExecutionReport(
        plan_id="plan_audit_ref", task_id=105, status="COMPLETED", total_steps=1,
        succeeded_steps_count=1, failed_steps_count=0, blocked_steps_count=0,
        step_results={"s1": step_res}, execution_order=["s1"], summary="Audit Ref"
    )
    handoff = KoshEpisodicHandoffController.process_plan_handoff(report, tenant_id="tenant_alice", vector_store=store)
    assert handoff.success is True
    indexed_chunk = store.get_chunk(handoff.chunk_ids[0])
    assert indexed_chunk.audit_trail_refs == ["evt_01J_SYS_STAT"]


# -------------------------------------------------------------
# 3. VERSIONING & TOMBSTONE TESTS (§9.6) (16-18)
# -------------------------------------------------------------

def test_16_document_versioning_update():
    store = KoshVectorStore()
    c1 = KoshChunk(chunk_id="c_v1", tenant_id="tenant_1", title="API Guide", content="v1", version=1)
    store.add_chunk(c1)
    c2 = KoshChunk(chunk_id="c_v1", tenant_id="tenant_1", title="API Guide", content="v2", version=2)
    store.add_chunk(c2)
    retrieved = store.get_chunk("c_v1")
    assert retrieved.version == 2
    assert retrieved.content == "v2"


def test_17_tombstone_soft_delete_exclusion():
    store = KoshVectorStore()
    chunk = KoshChunk(
        chunk_id="c_tomb", tenant_id="tenant_1", title="Old Policy", content="Old retirement rules",
        embedding=generate_deterministic_test_embedding("retirement rules")
    )
    store.add_chunk(chunk)
    
    # Active before tombstone
    q_vec = generate_deterministic_test_embedding("retirement rules")
    res1 = store.query(q_vec, tenant_id="tenant_1", min_similarity=0.0)
    assert len(res1) == 1

    # Apply tombstone (§9.6)
    store.tombstone_chunk("c_tomb", tenant_id="tenant_1")
    res2 = store.query(q_vec, tenant_id="tenant_1", min_similarity=0.0)
    assert len(res2) == 0


def test_18_cross_tenant_tombstone_denial():
    store = KoshVectorStore()
    chunk = KoshChunk(chunk_id="c_alice", tenant_id="tenant_alice", title="A", content="A")
    store.add_chunk(chunk)

    # Bob tries to tombstone Alice's chunk
    success = store.tombstone_chunk("c_alice", tenant_id="tenant_bob")
    assert success is False
    assert store.get_chunk("c_alice").is_tombstoned is False


# -------------------------------------------------------------
# 4. TENANT ISOLATION & SECURITY (§9.4, §18) (19-23)
# -------------------------------------------------------------

def test_19_cross_tenant_knowledge_isolation():
    service = KoshRetrievalService()
    service.vector_store.add_chunk(KoshChunk(
        chunk_id="c_alice_secret",
        tenant_id="tenant_alice",
        title="Alice Confidential Strategy",
        content="Secret project codename Phoenix Alpha",
        embedding=generate_deterministic_test_embedding("Secret project codename Phoenix Alpha")
    ))

    # Bob queries with the exact matching text
    bob_result = service.retrieve(
        query="Secret project codename Phoenix Alpha",
        tenant_id="tenant_bob",
        min_similarity=0.0
    )
    assert bob_result.results_count == 0
    assert len(bob_result.chunks) == 0

    # Alice queries and receives her chunk
    alice_result = service.retrieve(
        query="Secret project codename Phoenix Alpha",
        tenant_id="tenant_alice",
        min_similarity=0.0
    )
    assert alice_result.results_count == 1
    assert alice_result.chunks[0]["chunk_id"] == "c_alice_secret"


def test_20_cross_tenant_episodic_memory_isolation():
    service = KoshRetrievalService()
    service.vector_store.add_chunk(KoshChunk(
        chunk_id="ep_alice",
        tenant_id="tenant_alice",
        title="Alice Task 5 Execution Trace",
        content="Executed financial wire settlement $50,000",
        tier=MemoryTier.EPISODIC,
        embedding=generate_deterministic_test_embedding("Executed financial wire settlement $50,000")
    ))

    bob_res = service.retrieve(
        query="financial wire settlement",
        tenant_id="tenant_bob",
        tier_filter=[MemoryTier.EPISODIC],
        min_similarity=0.0
    )
    assert bob_res.results_count == 0


def test_21_global_knowledge_accessibility():
    service = KoshRetrievalService()
    service.vector_store.add_chunk(KoshChunk(
        chunk_id="c_global_handbook",
        tenant_id="global",
        title="Global Employee Handbook",
        content="Company standard operating procedures",
        embedding=generate_deterministic_test_embedding("standard operating procedures")
    ))

    res_alice = service.retrieve("standard operating procedures", tenant_id="tenant_alice", min_similarity=0.0)
    res_bob = service.retrieve("standard operating procedures", tenant_id="tenant_bob", min_similarity=0.0)
    assert res_alice.results_count == 1
    assert res_bob.results_count == 1


def test_22_empty_tenant_id_fails_closed():
    service = KoshRetrievalService()
    with pytest.raises(ValueError, match="Tenant ID is required"):
        service.retrieve("query", tenant_id="")


def test_23_empty_query_returns_zero_results():
    service = KoshRetrievalService()
    res = service.retrieve("", tenant_id="tenant_alice")
    assert res.results_count == 0
    assert res.chunks == []


# -------------------------------------------------------------
# 5. CHITRA RETRIEVAL AUDIT TRAIL (§9.7, §8.2) (24-26)
# -------------------------------------------------------------

def test_24_kosh_chitra_retrieval_event_generation():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    service = KoshRetrievalService()
    service.vector_store.add_chunk(KoshChunk(
        chunk_id="doc_1", tenant_id=f"tenant_{u_a}", title="Doc 1", content="Cloud Architecture",
        embedding=generate_deterministic_test_embedding("Cloud Architecture")
    ))

    result = service.retrieve(
        query="Cloud Architecture",
        tenant_id=f"tenant_{u_a}",
        db_session=db,
        task_id=t_a,
        user_id=u_a
    )
    assert result.chitra_event_id is not None

    evt = db.query(ChitraEvent).filter(ChitraEvent.event_id == result.chitra_event_id).first()
    assert evt is not None
    assert evt.faculty == "KOSH"
    assert evt.event_type == "retrieval"
    assert evt.decision["results_count"] == 1
    db.close()


def test_25_chitra_retrieval_evidence_and_query_hash():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    service = KoshRetrievalService()
    service.vector_store.add_chunk(KoshChunk(
        chunk_id="chunk_aud", tenant_id=f"tenant_{u_a}", title="Audit Title", content="Audit Content",
        embedding=generate_deterministic_test_embedding("Audit Content")
    ))

    res = service.retrieve("Audit Content", tenant_id=f"tenant_{u_a}", db_session=db, task_id=t_a, user_id=u_a)
    evt = db.query(ChitraEvent).filter(ChitraEvent.event_id == res.chitra_event_id).first()
    assert evt.decision["retrieved_chunk_ids"] == ["chunk_aud"]
    assert evt.input_hash is not None
    db.close()


def test_26_cryptographic_chain_verification_on_kosh_events():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    service = KoshRetrievalService()
    service.vector_store.add_chunk(KoshChunk(
        chunk_id="c_crypto", tenant_id=f"tenant_{u_a}", title="Crypto", content="Data",
        embedding=generate_deterministic_test_embedding("Data")
    ))

    service.retrieve("Data", tenant_id=f"tenant_{u_a}", db_session=db, task_id=t_a, user_id=u_a)
    service.retrieve("Data again", tenant_id=f"tenant_{u_a}", db_session=db, task_id=t_a, user_id=u_a)

    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    assert v_res.chain_status == "VERIFIED"
    assert v_res.events_checked == 2
    db.close()


# -------------------------------------------------------------
# 6. CONCURRENCY, PIPELINE & BOUNDARY (27-30)
# -------------------------------------------------------------

def test_27_concurrent_multi_tenant_vector_queries():
    service = KoshRetrievalService()
    for i in range(10):
        service.vector_store.add_chunk(KoshChunk(
            chunk_id=f"c_{i}", tenant_id=f"tenant_{i % 3}", title=f"Title {i}", content=f"Content {i}",
            embedding=generate_deterministic_test_embedding(f"shared query {i}")
        ))

    def worker(tenant_idx: int):
        return service.retrieve(query="shared query", tenant_id=f"tenant_{tenant_idx}", min_similarity=0.0)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(worker, i % 3) for i in range(30)]
        results = [f.result() for f in futures]

    assert len(results) == 30
    assert all(r.results_count > 0 for r in results)


def test_28_concurrent_episodic_handoffs():
    store = KoshVectorStore()

    def run_handoff(task_id: int):
        step_res = KarmaStepExecutionResult(
            step_id="s1", action=f"act {task_id}", status="SUCCEEDED", tool_id="echo_formatter",
            output="done", chitra_event_id=f"evt_{task_id}", verification_status="VERIFIED",
            completion_validation={"is_valid": True, "no_silent_action_valid": True, "audit_trail_ref": f"evt_{task_id}"}
        )
        report = KarmaDAGExecutionReport(
            plan_id=f"plan_{task_id}", task_id=task_id, status="COMPLETED", total_steps=1,
            succeeded_steps_count=1, failed_steps_count=0, blocked_steps_count=0,
            step_results={"s1": step_res}, execution_order=["s1"], summary="Success"
        )
        return KoshEpisodicHandoffController.process_plan_handoff(report, tenant_id=f"tenant_{task_id}", vector_store=store)

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(run_handoff, t_id) for t_id in range(20)]
        results = [f.result() for f in futures]

    assert len(results) == 20
    assert all(r.success is True for r in results)
    assert len(store._chunks) == 20


def test_29_full_pipeline_phase7_to_phase10():
    u_a, t_a, _, _ = reset_sandbox()
    db = TestSession()

    executor = KarmaDAGExecutor(sleep_fn=fast_mock_sleep)
    s1 = KarmaStep(step_id="s1", action="calculate 25 * 4", expected_outcome="100", dependencies=[])
    plan = KarmaPlanDAG(task_id=t_a, summary="P7-P10 Integration", steps=[s1])

    # 1. Execute Plan through Phase 7, 8, 9
    report = executor.execute_plan(plan, caller_authority="LOW", db_session=db, user_id=u_a)
    assert report.status == "COMPLETED"

    # 2. Handoff to Phase 10 KOSH Episodic Memory
    service = KoshRetrievalService()
    handoff = KoshEpisodicHandoffController.process_plan_handoff(report, tenant_id=f"tenant_{u_a}", vector_store=service.vector_store)
    assert handoff.success is True
    assert handoff.status == "HANDOFF_INDEXED"

    # 3. Retrieve indexed episodic memory through KOSH
    query_res = service.retrieve(
        query="calculate 25 * 4",
        tenant_id=f"tenant_{u_a}",
        tier_filter=[MemoryTier.EPISODIC],
        min_similarity=0.0,
        db_session=db,
        task_id=t_a,
        user_id=u_a
    )
    assert query_res.results_count == 1
    assert "calculate 25 * 4" in query_res.chunks[0]["content"]

    # 4. Verify cryptographic chain with both RACHIT and KOSH events
    v_res = chitra_verifier.verify_task_chain(db, t_a, user_id=u_a)
    assert v_res.valid is True
    assert v_res.chain_status == "VERIFIED"
    assert v_res.events_checked == 2  # 1 RACHIT invocation + 1 KOSH retrieval
    db.close()


def test_30_phase11_boundary_check():
    service = KoshRetrievalService()
    assert not hasattr(service, "phase_11_governor")
    assert not hasattr(service, "dynamic_prompt_synthesis")


def run_all_30_phase10_tests():
    print("==================================================")
    print("KOSH PHASE 10: 30-SCENARIO MULTI-TIER KNOWLEDGE CORE")
    print("& EPISODIC MEMORY SUITE (WHITESHEET §§9.0-9.7)")
    print("Target Sandbox: sqlite:///./test_karma_phase10_sandbox.db")
    print("==================================================")

    test_1_knowledge_chunk_indexing_and_storage()
    print("  [PASS 1/30] Knowledge chunk indexing and storage.")

    test_2_768_dim_vector_representation()
    print("  [PASS 2/30] 768-dim vector representation.")

    test_3_cosine_similarity_computation()
    print("  [PASS 3/30] Cosine similarity computation.")

    test_4_orthogonal_and_identical_vectors_similarity()
    print("  [PASS 4/30] Orthogonal and identical vectors similarity.")

    test_5_semantic_similarity_threshold_filtering()
    print("  [PASS 5/30] Semantic similarity threshold filtering (§9.5).")

    test_6_top_k_ranking_and_truncation()
    print("  [PASS 6/30] Top-K ranking and truncation (§9.5).")

    test_7_tier_1_working_context_filtering()
    print("  [PASS 7/30] Tier 1 Working Context filtering (§9.2).")

    test_8_tier_2_episodic_memory_filtering()
    print("  [PASS 8/30] Tier 2 Episodic Memory filtering (§9.2).")

    test_9_tier_3_semantic_store_filtering()
    print("  [PASS 9/30] Tier 3 Semantic Corporate Store filtering (§9.2).")

    test_10_multi_tier_combined_query()
    print("  [PASS 10/30] Multi-tier combined query.")

    test_11_episodic_handoff_from_completed_plan()
    print("  [PASS 11/30] Episodic memory handoff from validated KARMA plan (§9.3).")

    test_12_episodic_handoff_rejected_on_failed_plan()
    print("  [PASS 12/30] Episodic handoff rejected on failed plan.")

    test_13_episodic_handoff_rejected_on_unverified_step()
    print("  [PASS 13/30] Episodic handoff rejected on unverified step.")

    test_14_episodic_handoff_rejected_on_missing_no_silent_action_evidence()
    print("  [PASS 14/30] Episodic handoff rejected on missing NSA evidence (§7.9).")

    test_15_episodic_handoff_preserves_chitra_audit_references()
    print("  [PASS 15/30] Episodic handoff preserves CHITRA audit references.")

    test_16_document_versioning_update()
    print("  [PASS 16/30] Document versioning update (§9.6).")

    test_17_tombstone_soft_delete_exclusion()
    print("  [PASS 17/30] Tombstone soft-delete exclusion (§9.6).")

    test_18_cross_tenant_tombstone_denial()
    print("  [PASS 18/30] Cross-tenant tombstone modification denied.")

    test_19_cross_tenant_knowledge_isolation()
    print("  [PASS 19/30] Cross-tenant knowledge isolation (§9.4, §18).")

    test_20_cross_tenant_episodic_memory_isolation()
    print("  [PASS 20/30] Cross-tenant episodic memory isolation.")

    test_21_global_knowledge_accessibility()
    print("  [PASS 21/30] Global knowledge accessibility across tenants.")

    test_22_empty_tenant_id_fails_closed()
    print("  [PASS 22/30] Empty tenant ID fails closed.")

    test_23_empty_query_returns_zero_results()
    print("  [PASS 23/30] Empty query returns zero results.")

    test_24_kosh_chitra_retrieval_event_generation()
    print("  [PASS 24/30] KOSH CHITRA retrieval event generation (§9.7).")

    test_25_chitra_retrieval_evidence_and_query_hash()
    print("  [PASS 25/30] CHITRA retrieval evidence and query hash recorded.")

    test_26_cryptographic_chain_verification_on_kosh_events()
    print("  [PASS 26/30] Cryptographic chain verification on KOSH events.")

    test_27_concurrent_multi_tenant_vector_queries()
    print("  [PASS 27/30] Concurrent multi-tenant vector queries safety.")

    test_28_concurrent_episodic_handoffs()
    print("  [PASS 28/30] Concurrent episodic handoffs safety.")

    test_29_full_pipeline_phase7_to_phase10()
    print("  [PASS 29/30] Full pipeline: Phase 7 -> 8 -> 9 -> 10.")

    test_30_phase11_boundary_check()
    print("  [PASS 30/30] Phase 11 boundary verified (0 Phase 11 features).")

    print("\n==================================================")
    print("ALL 30 KOSH PHASE 10 TESTS PASSED 100% CLEANLY!")
    print("==================================================")


if __name__ == "__main__":
    run_all_30_phase10_tests()
