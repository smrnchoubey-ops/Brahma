"""
Migration script for SMRITI Memory schema (Phase 3A).
Migrates PostgreSQL table 'memory' to include tenant_id, user_id, session_id, task_id,
memory_type, metadata_payload, and updated_at with appropriate indexes.
"""
from sqlalchemy import text
from app.db.database import engine, Base
from app.models.user import User
from app.models.task import Task
from app.models.memory import Memory

def migrate_smriti_memory_schema():
    with engine.connect() as conn:
        print("Starting SMRITI Memory schema migration on PostgreSQL...")
        
        # 1. Create table if it doesn't exist
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS memory (
                id SERIAL PRIMARY KEY,
                tenant_id VARCHAR(64) NOT NULL DEFAULT 'global',
                user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                session_id VARCHAR(128),
                task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                memory_type VARCHAR(64) NOT NULL DEFAULT 'conversation',
                content TEXT NOT NULL,
                source VARCHAR(64) NOT NULL DEFAULT 'user',
                approved VARCHAR(32) NOT NULL DEFAULT 'APPROVED',
                metadata_payload JSONB,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """))
        conn.commit()

        # 2. Add any missing columns to existing table
        alter_queries = [
            "ALTER TABLE memory ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64) NOT NULL DEFAULT 'global';",
            "ALTER TABLE memory ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;",
            "ALTER TABLE memory ADD COLUMN IF NOT EXISTS session_id VARCHAR(128);",
            "ALTER TABLE memory ADD COLUMN IF NOT EXISTS task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL;",
            "ALTER TABLE memory ADD COLUMN IF NOT EXISTS memory_type VARCHAR(64) NOT NULL DEFAULT 'conversation';",
            "ALTER TABLE memory ADD COLUMN IF NOT EXISTS metadata_payload JSONB;",
            "ALTER TABLE memory ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;"
        ]

        for q in alter_queries:
            try:
                conn.execute(text(q))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Notice on query '{q}': {e}")

        # 3. Create indices for tenant-scoped querying
        index_queries = [
            "CREATE INDEX IF NOT EXISTS ix_memory_tenant_id ON memory(tenant_id);",
            "CREATE INDEX IF NOT EXISTS ix_memory_user_id ON memory(user_id);",
            "CREATE INDEX IF NOT EXISTS ix_memory_session_id ON memory(session_id);",
            "CREATE INDEX IF NOT EXISTS ix_memory_task_id ON memory(task_id);",
            "CREATE INDEX IF NOT EXISTS ix_memory_memory_type ON memory(memory_type);",
            "CREATE INDEX IF NOT EXISTS ix_memory_created_at ON memory(created_at);"
        ]

        for idx_q in index_queries:
            try:
                conn.execute(text(idx_q))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Notice on index query '{idx_q}': {e}")

        print("SMRITI Memory schema migration completed successfully.")

if __name__ == "__main__":
    migrate_smriti_memory_schema()
