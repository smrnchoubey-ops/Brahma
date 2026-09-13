"""
GAP #8 TEST SUITE: Federation Registry PostgreSQL Persistence
Whitesheet §18 (Federation Substrate) & §23 (Phase 4 Federation Roadmap)

Strictly validates:
1. Registration persistence to PostgreSQL ('federation_nodes' table).
2. Retrieval across fresh NodeTrustRegistry instantiations (process-restart proof).
3. Sequential trust-tier state machine persistence (UNTRUSTED -> VERIFIED -> FEDERATED) with DB updates.
4. Operational status persistence (ACTIVE -> SUSPENDED -> REVOKED) with DB updates.
5. Strict tenant isolation (Tenant A nodes invisible to Tenant B).
6. Missing-node behavior (get_node returns None, update raises KeyError).
7. Duplicate node registration rejection (ValueError).
8. Fail-closed behavior on database errors (no silent in-memory fallback).
9. Independent SQL verification of table schema, columns, indexes, and row state.
"""
import pytest
import uuid
import secrets
from datetime import datetime, timezone
from sqlalchemy import text
from unittest.mock import patch

from app.db.database import SessionLocal, engine
from app.models.federation_node import FederationNode
from app.core.federation.models import NodeIdentity, TrustTier, NodeStatus
from app.core.federation.identity import NodeIdentityManager
from app.core.federation.trust import NodeTrustRegistry, TrustTransitionError


@pytest.fixture(autouse=True)
def ensure_postgresql():
    """Mandatory preflight assertion that database is genuine PostgreSQL."""
    assert engine.dialect.name == "postgresql", f"Gap #8 requires PostgreSQL dialect, found '{engine.dialect.name}'"


@pytest.fixture
def clean_test_tenants():
    """Generates unique isolated tenant IDs and ensures database cleanup after tests."""
    tenant_a = f"tenant_gap8_a_{secrets.token_hex(4)}"
    tenant_b = f"tenant_gap8_b_{secrets.token_hex(4)}"
    yield tenant_a, tenant_b

    with SessionLocal() as db:
        db.query(FederationNode).filter(FederationNode.tenant_id.in_([tenant_a, tenant_b])).delete(synchronize_session=False)
        db.commit()


def test_1_registration_persists_to_postgresql(clean_test_tenants):
    """
    Validates that register_node() writes a row directly into the PostgreSQL 'federation_nodes' table.
    """
    tenant_a, _ = clean_test_tenants
    registry = NodeTrustRegistry(tenant_id=tenant_a)

    identity, _ = NodeIdentityManager.create_node_identity(
        name="Node_Alpha_Persist",
        trust_tier=TrustTier.UNTRUSTED,
        endpoint="https://node-alpha.brahma.mesh:8443",
        metadata={"region": "ap-south-1", "datacenter": "dc-01"},
        tenant_id=tenant_a
    )

    registry.register_node(identity)

    # Verify directly via PostgreSQL session
    with SessionLocal() as db:
        row = db.query(FederationNode).filter(FederationNode.node_id == identity.node_id).first()
        assert row is not None, "Node record was not persisted to PostgreSQL 'federation_nodes' table!"
        assert row.node_id == identity.node_id
        assert row.tenant_id == tenant_a
        assert row.public_key == identity.public_key
        assert row.trust_tier == "UNTRUSTED"
        assert row.status == "ACTIVE"
        assert row.name == "Node_Alpha_Persist"
        assert row.endpoint == "https://node-alpha.brahma.mesh:8443"
        assert row.node_metadata == {"region": "ap-south-1", "datacenter": "dc-01"}
        assert row.created_at is not None
        assert row.updated_at is not None


def test_2_process_restart_persistence_proof(clean_test_tenants):
    """
    Mandatory Section F Process-Restart Persistence Test:
    1. Register node in instance 1.
    2. Verify row in PostgreSQL.
    3. Create fresh registry instance 2 (simulating process restart).
    4. Retrieve same node and verify fields match.
    5. Update trust tier in instance 2.
    6. Create fresh registry instance 3.
    7. Verify updated trust tier is present in instance 3.
    """
    tenant_a, _ = clean_test_tenants

    # Step 1: Register in initial instance
    registry_1 = NodeTrustRegistry(tenant_id=tenant_a)
    identity, _ = NodeIdentityManager.create_node_identity(
        name="Node_Restart_Proof",
        trust_tier=TrustTier.UNTRUSTED,
        tenant_id=tenant_a
    )
    registry_1.register_node(identity)

    # Step 2: Verify PostgreSQL row directly
    with SessionLocal() as db:
        row = db.query(FederationNode).filter(FederationNode.node_id == identity.node_id).first()
        assert row is not None
        assert row.trust_tier == "UNTRUSTED"

    # Step 3 & 4: Instantiate NEW registry (Instance 2) and retrieve
    registry_2 = NodeTrustRegistry(tenant_id=tenant_a)
    fetched_node_2 = registry_2.get_node(identity.node_id)
    assert fetched_node_2 is not None, "Fresh registry instance failed to load persisted node from PostgreSQL!"
    assert fetched_node_2.node_id == identity.node_id
    assert fetched_node_2.name == "Node_Restart_Proof"
    assert fetched_node_2.trust_tier == TrustTier.UNTRUSTED

    # Step 5: Update trust tier in Instance 2
    updated_in_2 = registry_2.update_trust_tier(
        identity.node_id,
        TrustTier.VERIFIED,
        reason="Cryptographic challenge handshake verified"
    )
    assert updated_in_2.trust_tier == TrustTier.VERIFIED

    # Step 6 & 7: Instantiate NEW registry (Instance 3) and verify updated state persists
    registry_3 = NodeTrustRegistry(tenant_id=tenant_a)
    fetched_node_3 = registry_3.get_node(identity.node_id)
    assert fetched_node_3 is not None
    assert fetched_node_3.trust_tier == TrustTier.VERIFIED
    assert fetched_node_3.metadata.get("last_trust_change") is not None
    assert fetched_node_3.metadata["last_trust_change"]["from"] == "UNTRUSTED"
    assert fetched_node_3.metadata["last_trust_change"]["to"] == "VERIFIED"


def test_3_trust_tier_sequential_state_machine_persistence(clean_test_tenants):
    """
    Validates sequential trust tier progression:
    UNTRUSTED -> VERIFIED -> FEDERATED
    and ensures each transition is immediately committed to PostgreSQL.
    """
    tenant_a, _ = clean_test_tenants
    registry = NodeTrustRegistry(tenant_id=tenant_a)

    identity, _ = NodeIdentityManager.create_node_identity(
        name="Node_Trust_Progression",
        trust_tier=TrustTier.UNTRUSTED,
        tenant_id=tenant_a
    )
    registry.register_node(identity)

    # 1. Transition: UNTRUSTED -> VERIFIED
    registry.update_trust_tier(identity.node_id, TrustTier.VERIFIED, reason="KYN Passed")
    with SessionLocal() as db:
        row = db.query(FederationNode).filter(FederationNode.node_id == identity.node_id).first()
        assert row.trust_tier == "VERIFIED"
        assert row.node_metadata["last_trust_change"]["to"] == "VERIFIED"

    # 2. Transition: VERIFIED -> FEDERATED
    registry.update_trust_tier(identity.node_id, TrustTier.FEDERATED, reason="Mesh Peering Accord Signed")
    with SessionLocal() as db:
        row = db.query(FederationNode).filter(FederationNode.node_id == identity.node_id).first()
        assert row.trust_tier == "FEDERATED"
        assert row.node_metadata["last_trust_change"]["to"] == "FEDERATED"

    # 3. Illegal Jump: Cannot skip back to SOVEREIGN from UNTRUSTED directly
    identity_bad, _ = NodeIdentityManager.create_node_identity(tenant_id=tenant_a)
    registry.register_node(identity_bad)
    with pytest.raises(TrustTransitionError, match="Illegal trust escalation"):
        registry.update_trust_tier(identity_bad.node_id, TrustTier.FEDERATED)


def test_4_status_lifecycle_persistence(clean_test_tenants):
    """
    Validates operational status transitions:
    ACTIVE -> SUSPENDED -> REVOKED
    and confirms persistent DB state and trust rejection on non-active nodes.
    """
    tenant_a, _ = clean_test_tenants
    registry = NodeTrustRegistry(tenant_id=tenant_a)

    identity, _ = NodeIdentityManager.create_node_identity(
        name="Node_Status_Lifecycle",
        trust_tier=TrustTier.UNTRUSTED,
        tenant_id=tenant_a
    )
    registry.register_node(identity)
    registry.update_trust_tier(identity.node_id, TrustTier.VERIFIED)

    # 1. Suspend
    registry.set_node_status(identity.node_id, NodeStatus.SUSPENDED, reason="Scheduled Maintenance")
    assert registry.is_node_trusted(identity.node_id) is False

    with SessionLocal() as db:
        row = db.query(FederationNode).filter(FederationNode.node_id == identity.node_id).first()
        assert row.status == "SUSPENDED"
        assert row.node_metadata["last_status_change"]["to"] == "SUSPENDED"

    # 2. Revoke
    registry.set_node_status(identity.node_id, NodeStatus.REVOKED, reason="Compromised Key Material")
    assert registry.is_node_trusted(identity.node_id) is False

    with SessionLocal() as db:
        row = db.query(FederationNode).filter(FederationNode.node_id == identity.node_id).first()
        assert row.status == "REVOKED"
        assert row.node_metadata["last_status_change"]["to"] == "REVOKED"

    # 3. Cannot update trust tier when REVOKED
    with pytest.raises(TrustTransitionError, match="Cannot update trust tier"):
        registry.update_trust_tier(identity.node_id, TrustTier.FEDERATED)


def test_5_strict_tenant_isolation(clean_test_tenants):
    """
    Strictly validates multi-tenant isolation:
    - Tenant A registers Node_A.
    - Tenant B registers Node_B.
    - Tenant A cannot retrieve or list Node_B.
    - Tenant B cannot retrieve or list Node_A.
    - Cross-tenant updates are rejected with KeyError.
    """
    tenant_a, tenant_b = clean_test_tenants

    reg_a = NodeTrustRegistry(tenant_id=tenant_a)
    reg_b = NodeTrustRegistry(tenant_id=tenant_b)

    identity_a, _ = NodeIdentityManager.create_node_identity(name="Node_A_Only", tenant_id=tenant_a)
    identity_b, _ = NodeIdentityManager.create_node_identity(name="Node_B_Only", tenant_id=tenant_b)

    reg_a.register_node(identity_a)
    reg_b.register_node(identity_b)

    # Tenant A access checks
    assert reg_a.get_node(identity_a.node_id) is not None
    assert reg_a.get_node(identity_b.node_id) is None, "Tenant A accessed Tenant B's node (SECURITY BREACH)!"
    assert len(reg_a.list_nodes()) == 1
    assert reg_a.list_nodes()[0].node_id == identity_a.node_id

    # Tenant B access checks
    assert reg_b.get_node(identity_b.node_id) is not None
    assert reg_b.get_node(identity_a.node_id) is None, "Tenant B accessed Tenant A's node (SECURITY BREACH)!"
    assert len(reg_b.list_nodes()) == 1
    assert reg_b.list_nodes()[0].node_id == identity_b.node_id

    # Cross-tenant modification rejection
    with pytest.raises(KeyError, match="not registered"):
        reg_a.update_trust_tier(identity_b.node_id, TrustTier.VERIFIED)

    with pytest.raises(KeyError, match="not registered"):
        reg_b.set_node_status(identity_a.node_id, NodeStatus.REVOKED)


def test_6_missing_and_duplicate_node_handling(clean_test_tenants):
    """
    Validates fail-closed semantics for:
    - Non-existent node lookups (returns None)
    - Empty node_id lookups (returns None)
    - Non-existent node updates (raises KeyError)
    - Duplicate node registration rejection (raises ValueError)
    """
    tenant_a, _ = clean_test_tenants
    registry = NodeTrustRegistry(tenant_id=tenant_a)

    assert registry.get_node("node_nonexistent_999") is None
    assert registry.get_node("") is None
    assert registry.get_node("   ") is None

    with pytest.raises(KeyError):
        registry.update_trust_tier("node_nonexistent_999", TrustTier.VERIFIED)

    identity, _ = NodeIdentityManager.create_node_identity(tenant_id=tenant_a)
    registry.register_node(identity)

    # Duplicate registration rejected
    with pytest.raises(ValueError, match="Duplicate node registration rejected"):
        registry.register_node(identity)


def test_7_database_failure_fails_closed_without_silent_fallback(clean_test_tenants):
    """
    Validates Rule 1: No silent in-memory fallback when PostgreSQL fails.
    If database query or commit fails, it must re-raise the exception.
    """
    tenant_a, _ = clean_test_tenants
    registry = NodeTrustRegistry(tenant_id=tenant_a)
    identity, _ = NodeIdentityManager.create_node_identity(tenant_id=tenant_a)

    # Simulate database connection failure
    with patch("app.core.federation.trust.SessionLocal", side_effect=RuntimeError("PostgreSQL connection lost")):
        with pytest.raises(RuntimeError, match="PostgreSQL connection lost"):
            registry.register_node(identity)

    with patch("app.core.federation.trust.SessionLocal", side_effect=RuntimeError("PostgreSQL connection lost")):
        with pytest.raises(RuntimeError, match="PostgreSQL connection lost"):
            registry.get_node("some_node_id")


def test_8_direct_sql_schema_and_column_verification():
    """
    Direct raw SQL assertion verifying table structure, columns, and index constraints.
    """
    with engine.connect() as conn:
        # 1. Verify table exists in PostgreSQL
        res = conn.execute(text("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'federation_nodes';
        """)).fetchall()
        assert len(res) == 1, "Table 'federation_nodes' does not exist in PostgreSQL!"

        # 2. Verify required columns and types
        columns_res = conn.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'federation_nodes';
        """)).fetchall()
        cols = {row[0]: (row[1], row[2]) for row in columns_res}

        assert "id" in cols
        assert "node_id" in cols and cols["node_id"][1] == "NO"
        assert "tenant_id" in cols and cols["tenant_id"][1] == "NO"
        assert "public_key" in cols and cols["public_key"][1] == "NO"
        assert "trust_tier" in cols and cols["trust_tier"][1] == "NO"
        assert "status" in cols and cols["status"][1] == "NO"
        assert "name" in cols
        assert "endpoint" in cols
        assert "node_metadata" in cols and cols["node_metadata"][0] == "jsonb"
        assert "created_at" in cols
        assert "updated_at" in cols

        # 3. Verify indexes exist
        indexes_res = conn.execute(text("""
            SELECT indexname FROM pg_indexes WHERE tablename = 'federation_nodes';
        """)).fetchall()
        index_names = [r[0] for r in indexes_res]

        assert "ix_federation_nodes_node_id" in index_names or "federation_nodes_node_id_key" in index_names
        assert "ix_federation_nodes_tenant_id" in index_names
