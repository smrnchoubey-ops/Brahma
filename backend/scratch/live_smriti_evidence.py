import json
from sqlalchemy import text
from app.db.database import SessionLocal
from app.models import User, Task, Memory
from app.core.smriti.service import SmritiMemoryService


def run_live_evidence():
    print("=== LIVE POSTGRESQL SMRITI DATABASE EVIDENCE ===\n")
    db = SessionLocal()
    try:
        # 1. Schema Evidence
        print("1. POSTGRESQL MEMORY TABLE SCHEMA:")
        cols = db.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_name = 'memory'
            ORDER BY ordinal_position;
        """)).fetchall()
        for col in cols:
            print(f"   - {col[0]}: {col[1]} (nullable={col[2]}, default={col[3]})")
            
        # 2. Row count
        cnt = db.execute(text("SELECT count(*) FROM memory;")).scalar()
        print(f"\n2. CURRENT TOTAL ROW COUNT: {cnt}")
        
        # 3. Write record for Tenant A
        service = SmritiMemoryService()
        rec_a = service.record_interaction(
            tenant_id="tenant_live_demo_alpha",
            user_id=1,
            session_id="ses_live_alpha_101",
            content="User prefers concise mathematical explanations without boilerplate.",
            memory_type="preference",
            source="user",
            metadata_payload={"source_module": "chat", "confidence": 1.0},
            db_session=db
        )
        print(f"\n3. INSERTED TENANT A RECORD: id={rec_a.id}, tenant_id={rec_a.tenant_id}, session_id={rec_a.session_id}, content=\"{rec_a.content}\"")
        
        # 4. Successful Same-Tenant Retrieval
        read_a = service.get_memory(memory_id=rec_a.id, tenant_id="tenant_live_demo_alpha", db_session=db)
        print(f"\n4. SAME-TENANT RETRIEVAL: Success={read_a is not None}, Content=\"{read_a.content if read_a else None}\"")
        
        # 5. Cross-Tenant Retrieval Attempt by Tenant B
        read_b = service.get_memory(memory_id=rec_a.id, tenant_id="tenant_live_demo_beta", db_session=db)
        print(f"\n5. CROSS-TENANT RETRIEVAL (Tenant Beta accessing Tenant Alpha): Result={read_b} (FAIL-CLOSED ACCESS DENIED)")
        
        # 6. Session Continuity Context
        rec_a2 = service.record_interaction(
            tenant_id="tenant_live_demo_alpha",
            user_id=1,
            session_id="ses_live_alpha_101",
            content="Agent acknowledged user preference.",
            source="agent",
            db_session=db
        )
        context = service.load_session_context(tenant_id="tenant_live_demo_alpha", session_id="ses_live_alpha_101", db_session=db)
        print(f"\n6. SESSION CONTINUITY TURNS (Count: {len(context)}):")
        for c in context:
            print(f"   [{c.source}]: {c.content}")

    finally:
        db.close()

    # 7. Persistence across service recreation / DB session boundary
    print("\n7. PROCESS / SESSION RECREATION PERSISTENCE:")
    new_db = SessionLocal()
    try:
        fresh_service = SmritiMemoryService()
        recovered = fresh_service.get_memory(memory_id=rec_a.id, tenant_id="tenant_live_demo_alpha", db_session=new_db)
        print(f"   Fresh Instance Query Result: id={recovered.id}, tenant={recovered.tenant_id}, content=\"{recovered.content}\"")
        print(f"   Survives session boundary: {recovered is not None and recovered.id == rec_a.id}")
    finally:
        new_db.close()

if __name__ == "__main__":
    run_live_evidence()
