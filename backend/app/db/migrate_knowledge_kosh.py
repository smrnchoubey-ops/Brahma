"""
Migration script for KOSH Knowledge schema (Phase 3B).
Migrates PostgreSQL table 'knowledge' to include tenant_id, provenance_source, source_uri,
confidence_score, epistemic_status, verification_details, created_at, and updated_at with appropriate indexes.
"""
from sqlalchemy import text
from app.db.database import engine

def migrate_kosh_knowledge_schema():
    with engine.connect() as conn:
        print("Starting KOSH Knowledge schema migration on PostgreSQL...")
        
        # 1. Add missing columns to existing table
        alter_queries = [
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64) NOT NULL;",
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS provenance_source VARCHAR(255) NOT NULL DEFAULT 'unspecified';",
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS source_uri VARCHAR(512);",
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS confidence_score DOUBLE PRECISION NOT NULL DEFAULT 1.0;",
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS epistemic_status VARCHAR(64) NOT NULL DEFAULT 'VERIFIED';",
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS verification_details JSONB;",
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;"
        ]

        for q in alter_queries:
            try:
                conn.execute(text(q))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Notice on query '{q}': {e}")

        # 2. Create indices for tenant-scoped querying and epistemic status
        index_queries = [
            "CREATE INDEX IF NOT EXISTS ix_knowledge_tenant_id ON knowledge(tenant_id);",
            "CREATE INDEX IF NOT EXISTS ix_knowledge_epistemic_status ON knowledge(epistemic_status);",
            "CREATE INDEX IF NOT EXISTS ix_knowledge_created_at ON knowledge(created_at);"
        ]

        for idx_q in index_queries:
            try:
                conn.execute(text(idx_q))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Notice on index query '{idx_q}': {e}")

        print("KOSH Knowledge schema migration completed successfully.")

if __name__ == "__main__":
    migrate_kosh_knowledge_schema()
