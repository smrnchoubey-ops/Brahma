"""
Phase 3A SMRITI Foundation Test Suite (Whitesheet §5 F5 Temporal Memory, §4.1 Path 2, §13 / CA-008).
Tests PostgreSQL persistent memory storage, strict tenant isolation, session context continuity,
cross-tenant access denial, fail-closed behavior, and process restart durability.
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy import text

from app.db.database import SessionLocal, engine
from app.models.user import User
from app.models.task import Task
from app.models.memory import Memory
from app.core.smriti.service import SmritiMemoryService, smriti_service
from app.core.smriti.models import SmritiQuery


def setup_module():
    """Ensure schema is migrated before running tests."""
    from app.db.migrate_memory_smriti import migrate_smriti_memory_schema
    migrate_smriti_memory_schema()


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_1_postgresql_schema_has_required_ownership_columns(db_session):
    """Verifies that the PostgreSQL memory table schema has all tenant/user/session ownership columns."""
    cols = db_session.execute(text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'memory';
    """)).fetchall()
    column_names = {c[0] for c in cols}

    assert "id" in column_names
    assert "tenant_id" in column_names
    assert "user_id" in column_names
    assert "session_id" in column_names
    assert "task_id" in column_names
    assert "memory_type" in column_names
    assert "content" in column_names
    assert "source" in column_names
    assert "metadata_payload" in column_names
    assert "created_at" in column_names
    assert "updated_at" in column_names


def test_2_write_memory_for_tenant_a(db_session):
    """Writes a memory entry bound to Tenant A and verifies database persistence."""
    service = SmritiMemoryService()
    record = service.record_interaction(
        tenant_id="tenant_alice_smriti_01",
        content="Alice preference: always format numbers with commas.",
        session_id="ses_alice_001",
        memory_type="preference",
        source="user",
        metadata_payload={"priority": "high"},
        db_session=db_session
    )

    assert record.id is not None
    assert record.tenant_id == "tenant_alice_smriti_01"
    assert record.session_id == "ses_alice_001"
    assert record.content == "Alice preference: always format numbers with commas."

    # Direct DB inspection
    db_row = db_session.query(Memory).filter(Memory.id == record.id).first()
    assert db_row is not None
    assert db_row.tenant_id == "tenant_alice_smriti_01"
    assert db_row.metadata_payload.get("priority") == "high"


def test_3_read_memory_from_tenant_a_succeeds(db_session):
    """Reads previously written memory within the same tenant context."""
    service = SmritiMemoryService()
    record = service.record_interaction(
        tenant_id="tenant_alice_smriti_02",
        content="Secret project codename is Project Garuda.",
        session_id="ses_alice_002",
        memory_type="fact",
        db_session=db_session
    )

    retrieved = service.get_memory(
        memory_id=record.id,
        tenant_id="tenant_alice_smriti_02",
        db_session=db_session
    )
    assert retrieved is not None
    assert retrieved.id == record.id
    assert retrieved.content == "Secret project codename is Project Garuda."


def test_4_cross_tenant_read_fails_closed(db_session):
    """Attempt by Tenant B to read Tenant A's memory record MUST return None (fail-closed)."""
    service = SmritiMemoryService()
    record_a = service.record_interaction(
        tenant_id="tenant_alice_smriti_03",
        content="Alice confidential budget is $500,000.",
        session_id="ses_alice_003",
        db_session=db_session
    )

    # Tenant Bob attempts to access Alice's record
    bob_attempt = service.get_memory(
        memory_id=record_a.id,
        tenant_id="tenant_bob_smriti_03",
        db_session=db_session
    )
    assert bob_attempt is None, "Security Violation: Tenant Bob was able to retrieve Tenant Alice's memory!"


def test_5_cross_tenant_delete_and_update_fails_closed(db_session):
    """Attempt by Tenant B to update or delete Tenant A's memory record MUST fail closed."""
    service = SmritiMemoryService()
    record_a = service.record_interaction(
        tenant_id="tenant_alice_smriti_04",
        content="Original Alice Note.",
        db_session=db_session
    )

    # Bob attempts to update Alice's memory
    update_res = service.repository.update_memory(
        db=db_session,
        memory_id=record_a.id,
        tenant_id="tenant_bob_smriti_04",
        content="Tampered by Bob"
    )
    assert update_res is False

    # Verify content was NOT tampered
    unmodified = service.get_memory(memory_id=record_a.id, tenant_id="tenant_alice_smriti_04", db_session=db_session)
    assert unmodified.content == "Original Alice Note."

    # Bob attempts to delete Alice's memory
    del_res = service.delete_memory(
        memory_id=record_a.id,
        tenant_id="tenant_bob_smriti_04",
        db_session=db_session
    )
    assert del_res is False

    # Verify record still exists for Alice
    still_exists = service.get_memory(memory_id=record_a.id, tenant_id="tenant_alice_smriti_04", db_session=db_session)
    assert still_exists is not None


def test_6_persistence_across_service_recreation(db_session):
    """Verifies that memory records persist in PostgreSQL when a fresh service and DB session are instantiated."""
    # Write with Service Instance 1
    service_1 = SmritiMemoryService()
    rec = service_1.record_interaction(
        tenant_id="tenant_durable_01",
        content="Durable statement: System must survive restart.",
        session_id="ses_durable_01",
        db_session=db_session
    )
    saved_id = rec.id
    db_session.close()

    # Recreate brand new DB session & brand new Service instance (simulating restart)
    new_db = SessionLocal()
    try:
        fresh_service = SmritiMemoryService()
        recovered = fresh_service.get_memory(
            memory_id=saved_id,
            tenant_id="tenant_durable_01",
            db_session=new_db
        )
        assert recovered is not None
        assert recovered.id == saved_id
        assert recovered.content == "Durable statement: System must survive restart."
    finally:
        new_db.close()


def test_7_missing_or_empty_tenant_fails_closed(db_session):
    """Missing or empty tenant_id must immediately raise ValueError (fail-closed)."""
    service = SmritiMemoryService()

    with pytest.raises(ValueError, match="tenant_id is missing"):
        service.record_interaction(
            tenant_id="",
            content="Invalid write without tenant",
            db_session=db_session
        )

    with pytest.raises(ValueError, match="tenant_id is missing"):
        service.get_memory(
            memory_id=1,
            tenant_id="",
            db_session=db_session
        )

    with pytest.raises(ValueError, match="tenant_id is missing"):
        service.load_session_context(
            tenant_id="   ",
            session_id="ses_1",
            db_session=db_session
        )


def test_8_session_continuity_chronological_retrieval(db_session):
    """Verifies F5 Temporal Memory session context continuity within a tenant boundary."""
    service = SmritiMemoryService()
    t_id = "tenant_continuity_01"
    s_id = "ses_continuity_chat_99"

    # Insert 3 sequential interaction turns
    m1 = service.record_interaction(tenant_id=t_id, session_id=s_id, content="User: Hello, my name is Dave.", source="user", db_session=db_session)
    m2 = service.record_interaction(tenant_id=t_id, session_id=s_id, content="Agent: Hello Dave, how can I assist you today?", source="agent", db_session=db_session)
    m3 = service.record_interaction(tenant_id=t_id, session_id=s_id, content="User: What is the current system status?", source="user", db_session=db_session)

    # Load session context
    history = service.load_session_context(tenant_id=t_id, session_id=s_id, db_session=db_session)
    assert len(history) >= 3
    contents = [h.content for h in history]
    assert "User: Hello, my name is Dave." in contents
    assert "Agent: Hello Dave, how can I assist you today?" in contents
    assert "User: What is the current system status?" in contents
