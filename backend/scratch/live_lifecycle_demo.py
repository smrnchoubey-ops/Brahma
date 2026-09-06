import sys
sys.path.insert(0, ".")
from app.db.database import SessionLocal, engine
from app.core.kosh.service import kosh_service
from sqlalchemy import text

def demo_lifecycle_row():
    db = SessionLocal()
    tenant_id = "tenant_demo_lifecycle_10"
    
    try:
        # Step 1: INGESTION
        item = kosh_service.ingest(
            tenant_id=tenant_id,
            title="Lifecycle State Transition Demo",
            content="Demonstrating exact row state transitions in PostgreSQL",
            provenance_source="Verification Suite",
            confidence_score=0.95,
            db_session=db
        )
        item_id = item.id
        db.commit()
        
        row1 = db.execute(text("SELECT id, title, lifecycle_state, validated_at, reviewed_at, constitutional_verdict, activated_at, deprecated_at FROM knowledge WHERE id = :id"), {"id": item_id}).fetchone()
        print("STAGE 1 - INGESTION:")
        print(dict(row1._mapping))
        
        # Step 2: VALIDATION
        kosh_service.validate(knowledge_id=item_id, tenant_id=tenant_id, db_session=db)
        db.commit()
        
        row2 = db.execute(text("SELECT id, title, lifecycle_state, validated_at, reviewed_at, constitutional_verdict, activated_at, deprecated_at FROM knowledge WHERE id = :id"), {"id": item_id}).fetchone()
        print("\nSTAGE 2 - VALIDATION:")
        print(dict(row2._mapping))
        
        # Step 3: CONSTITUTIONAL_REVIEW
        kosh_service.constitutional_review(knowledge_id=item_id, tenant_id=tenant_id, verdict="PASSED", db_session=db)
        db.commit()
        
        row3 = db.execute(text("SELECT id, title, lifecycle_state, validated_at, reviewed_at, constitutional_verdict, activated_at, deprecated_at FROM knowledge WHERE id = :id"), {"id": item_id}).fetchone()
        print("\nSTAGE 3 - CONSTITUTIONAL_REVIEW:")
        print(dict(row3._mapping))
        
        # Step 4: ACTIVE
        kosh_service.activate(knowledge_id=item_id, tenant_id=tenant_id, db_session=db)
        db.commit()
        
        row4 = db.execute(text("SELECT id, title, lifecycle_state, validated_at, reviewed_at, constitutional_verdict, activated_at, deprecated_at FROM knowledge WHERE id = :id"), {"id": item_id}).fetchone()
        print("\nSTAGE 4 - ACTIVE:")
        print(dict(row4._mapping))
        
    finally:
        db.close()

if __name__ == "__main__":
    demo_lifecycle_row()
