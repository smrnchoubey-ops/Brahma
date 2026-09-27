"""
GAP #7 Adversarial & Cross-Tenant Knowledge Isolation Test Suite.
Validates:
1. Primary KOSH core engine (app/core/kosh/) tenant boundary isolation.
2. Legacy KOSH path (app/repositories/knowledge_repository.py & app/services/kosh_service.py) tenant boundary isolation.
3. Fail-closed rejection of missing, empty, whitespace, or invalid tenant_id.
4. Immunity to vector similarity collisions across tenant boundaries.
"""
import unittest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, DateTime, JSON
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.sql import func


from app.models.knowledge import Knowledge
from app.repositories.knowledge_repository import semantic_search as legacy_semantic_search
from app.services.kosh_service import KoshService
from app.services.pragya_service import PragyaService
from app.core.kosh.repository import KoshRepository
from app.core.kosh.service import KoshKnowledgeService
from app.core.kosh.retrieval_service import KoshRetrievalService
from app.core.kosh.vector_engine import KoshVectorStore, KoshChunk, MemoryTier, generate_deterministic_test_embedding
from agents.nodes.kosh import kosh_node

# Sandbox SQLite setup for mock/emulated DB tests
Base = declarative_base()

class SandboxKnowledge(Base):
    __tablename__ = "knowledge"
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    provenance_source = Column(String(255), default="unspecified", nullable=False)
    source_uri = Column(String(512), nullable=True)
    confidence_score = Column(Float, default=1.0, nullable=False)
    epistemic_status = Column(String(64), default="VERIFIED", nullable=False)
    verification_details = Column(JSON, nullable=True)
    lifecycle_state = Column(String(64), default="INGESTION", nullable=False)
    validated_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    constitutional_verdict = Column(String(64), nullable=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    deprecated_at = Column(DateTime(timezone=True), nullable=True)
    deprecation_reason = Column(String(512), nullable=True)
    lifecycle_history = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

sandbox_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
Base.metadata.create_all(bind=sandbox_engine)
SandboxSession = sessionmaker(bind=sandbox_engine)


# -------------------------------------------------------------
# 1. ADVERSARIAL VECTOR COLLISION TESTS
# -------------------------------------------------------------

def test_a_tenant_a_cannot_retrieve_tenant_b_similar_vector():
    """A. Tenant A querying with Tenant B's optimal vector receives ONLY Tenant A items."""
    store = KoshVectorStore()
    vec_a = [1.0, 0.0, 0.0, 0.0]
    vec_b = [0.999, 0.001, 0.0, 0.0]  # Deliberate vector collision (> 0.999 cosine similarity)

    chunk_a = KoshChunk(
        chunk_id="chk_a",
        tenant_id="tenant_alice",
        title="Alice Secret Formula",
        content="Compound Alpha 99",
        embedding=vec_a
    )
    chunk_b = KoshChunk(
        chunk_id="chk_b",
        tenant_id="tenant_bob",
        title="Bob Secret Formula",
        content="Compound Beta 77",
        embedding=vec_b
    )
    store.add_chunk(chunk_a)
    store.add_chunk(chunk_b)

    # Alice queries with vec_b (closest to Bob)
    results = store.query(query_vector=vec_b, tenant_id="tenant_alice", min_similarity=0.0)
    assert len(results) == 1
    assert results[0][0].tenant_id == "tenant_alice"
    assert results[0][0].chunk_id == "chk_a"


def test_b_tenant_b_cannot_retrieve_tenant_a_similar_vector():
    """B. Tenant B querying with Tenant A's optimal vector receives ONLY Tenant B items."""
    store = KoshVectorStore()
    vec_a = [1.0, 0.0, 0.0, 0.0]
    vec_b = [0.999, 0.001, 0.0, 0.0]

    chunk_a = KoshChunk(
        chunk_id="chk_a",
        tenant_id="tenant_alice",
        title="Alice Secret Formula",
        content="Compound Alpha 99",
        embedding=vec_a
    )
    chunk_b = KoshChunk(
        chunk_id="chk_b",
        tenant_id="tenant_bob",
        title="Bob Secret Formula",
        content="Compound Beta 77",
        embedding=vec_b
    )
    store.add_chunk(chunk_a)
    store.add_chunk(chunk_b)

    # Bob queries with vec_a (closest to Alice)
    results = store.query(query_vector=vec_a, tenant_id="tenant_bob", min_similarity=0.0)
    assert len(results) == 1
    assert results[0][0].tenant_id == "tenant_bob"
    assert results[0][0].chunk_id == "chk_b"


# -------------------------------------------------------------
# 2. FAIL-CLOSED VALIDATION TESTS (LEGACY & CORE)
# -------------------------------------------------------------

def test_c_missing_tenant_id_fails_closed_legacy_repository():
    """C. Missing tenant_id in legacy semantic_search fails closed."""
    db = MagicMock()
    failed_closed = False
    try:
        legacy_semantic_search(db=db, query="test query", tenant_id=None)
    except ValueError as e:
        if "Security Violation" in str(e) and "tenant_id" in str(e):
            failed_closed = True
    assert failed_closed, "Missing tenant_id did not raise Security Violation ValueError"


def test_d_empty_or_whitespace_tenant_id_fails_closed():
    """D. Empty/whitespace tenant_id in legacy semantic_search and KoshService fails closed."""
    db = MagicMock()

    # 1. Empty string in semantic_search
    failed_closed_empty = False
    try:
        legacy_semantic_search(db=db, query="test query", tenant_id="")
    except ValueError:
        failed_closed_empty = True
    assert failed_closed_empty

    # 2. Whitespace string in semantic_search
    failed_closed_ws = False
    try:
        legacy_semantic_search(db=db, query="test query", tenant_id="   ")
    except ValueError:
        failed_closed_ws = True
    assert failed_closed_ws

    # 3. KoshService.retrieve with empty tenant_id
    k_service = KoshService()
    failed_closed_service = False
    try:
        k_service.retrieve(query="test query", tenant_id="")
    except ValueError:
        failed_closed_service = True
    assert failed_closed_service

    # 4. PragyaService.answer with empty tenant_id
    pragya = PragyaService()
    failed_closed_pragya = False
    try:
        pragya.answer(query="test question", tenant_id="")
    except ValueError:
        failed_closed_pragya = True
    assert failed_closed_pragya



def test_e_invalid_tenant_id_returns_zero_results():
    """E. Invalid/unknown tenant_id receives 0 results without leaking other tenants."""
    store = KoshVectorStore()
    chunk_a = KoshChunk(
        chunk_id="chk_a",
        tenant_id="tenant_alice",
        title="Alice Secret",
        content="Alice Data",
        embedding=[1.0, 0.0]
    )
    store.add_chunk(chunk_a)

    results = store.query(query_vector=[1.0, 0.0], tenant_id="tenant_attacker_999", min_similarity=0.0)
    assert len(results) == 0


# -------------------------------------------------------------
# 3. RUNTIME & LEGACY PATH VERIFICATION
# -------------------------------------------------------------

def test_f_primary_kosh_runtime_node_unaffected():
    """F. Primary KOSH runtime path (kosh_node) remains unaffected and enforces tenant boundaries."""
    state_alice = {
        "intent": "policy information",
        "tenant_id": "tenant_alice",
        "task_id": 1001,
        "user_id": 1
    }

    class MockKoshCoreService:
        def query_active_knowledge(self, tenant_id, query_text=None, user_id=None):
            if tenant_id == "tenant_alice":
                mock_item = MagicMock()
                mock_item.title = "Alice Policy"
                mock_item.provenance_source = "corp_vault"
                mock_item.confidence_score = 0.95
                mock_item.content = "Alice confidential leave guidelines"
                return [mock_item]
            return []

    with patch("agents.nodes.kosh.kosh_service", MockKoshCoreService()), \
         patch("agents.nodes.kosh.log_audit_event", return_value=None):
        out = kosh_node(state_alice)
        assert out["status"] == "KOSH_SUCCESS"
        assert "Alice confidential leave guidelines" in out["knowledge_context"]


def test_g_legacy_kosh_path_now_tenant_scoped():
    """G. Legacy KOSH path (knowledge_repository.py & kosh_service.py) is now strictly tenant-scoped."""
    # Mock db.execute to inspect the executed parameterized SQL
    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_row = MagicMock()
    mock_row.title = "Alice Doc"
    mock_row.content = "Alice Content"
    mock_result.fetchall.return_value = [mock_row]
    mock_db.execute.return_value = mock_result

    with patch("app.repositories.knowledge_repository.generate_embedding", return_value=[0.1]*768):
        res = legacy_semantic_search(
            db=mock_db,
            query="test query",
            tenant_id="tenant_alice",
            top_k=5
        )

        assert len(res) == 1
        assert res[0]["title"] == "Alice Doc"

        # Verify SQL query contains WHERE tenant_id = :tenant_id
        assert mock_db.execute.called
        call_args = mock_db.execute.call_args
        sql_statement = str(call_args[0][0])
        params = call_args[0][1]

        assert "WHERE tenant_id = :tenant_id" in sql_statement
        assert params["tenant_id"] == "tenant_alice"
        assert params["top_k"] == 5


def run_all():
    print("==================================================")
    print("RUNNING ADVERSARIAL & LEGACY KOSH AUDIT TESTS")
    print("==================================================")
    test_a_tenant_a_cannot_retrieve_tenant_b_similar_vector()
    print("  [PASS A] Tenant A cannot retrieve Tenant B's similar vector.")
    test_b_tenant_b_cannot_retrieve_tenant_a_similar_vector()
    print("  [PASS B] Tenant B cannot retrieve Tenant A's similar vector.")
    test_c_missing_tenant_id_fails_closed_legacy_repository()
    print("  [PASS C] Missing tenant_id fails closed in legacy repository.")
    test_d_empty_or_whitespace_tenant_id_fails_closed()
    print("  [PASS D] Empty/whitespace tenant_id fails closed across services.")
    test_e_invalid_tenant_id_returns_zero_results()
    print("  [PASS E] Invalid tenant_id returns zero rows.")
    test_f_primary_kosh_runtime_node_unaffected()
    print("  [PASS F] Primary KOSH runtime path remains unaffected.")
    test_g_legacy_kosh_path_now_tenant_scoped()
    print("  [PASS G] Legacy KOSH path verified strictly tenant-scoped at SQL boundary.")
    print("==================================================")
    print("ALL GAP #7 ADVERSARIAL TESTS PASSED!")
    print("==================================================")


if __name__ == "__main__":
    run_all()
