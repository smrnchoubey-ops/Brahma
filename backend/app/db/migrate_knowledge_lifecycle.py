"""
Migration script for KOSH Knowledge Lifecycle schema (Phase 3C / Whitesheet §16).
Migrates PostgreSQL table 'knowledge' to include:
- lifecycle_state (VARCHAR(64) NOT NULL DEFAULT 'INGESTION')
- validated_at (TIMESTAMP WITH TIME ZONE)
- reviewed_at (TIMESTAMP WITH TIME ZONE)
- constitutional_verdict (VARCHAR(64))
- activated_at (TIMESTAMP WITH TIME ZONE)
- deprecated_at (TIMESTAMP WITH TIME ZONE)
- deprecation_reason (VARCHAR(512))
- lifecycle_history (JSONB)
with appropriate indices for fast tenant-scoped lifecycle filtering.
"""
from sqlalchemy import text
from app.db.database import engine


def migrate_knowledge_lifecycle_schema():
    with engine.connect() as conn:
        print("Starting KOSH Knowledge Lifecycle schema migration on PostgreSQL...")

        # 1. Add missing lifecycle columns to knowledge table
        alter_queries = [
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS lifecycle_state VARCHAR(64) NOT NULL DEFAULT 'INGESTION';",
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS validated_at TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS constitutional_verdict VARCHAR(64);",
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS activated_at TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS deprecated_at TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS deprecation_reason VARCHAR(512);",
            "ALTER TABLE knowledge ADD COLUMN IF NOT EXISTS lifecycle_history JSONB DEFAULT '[]'::jsonb;"
        ]

        for q in alter_queries:
            try:
                conn.execute(text(q))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Notice on query '{q}': {e}")

        # 2. Create indices for lifecycle state and tenant-scoped lifecycle lookups
        index_queries = [
            "CREATE INDEX IF NOT EXISTS ix_knowledge_lifecycle_state ON knowledge(lifecycle_state);",
            "CREATE INDEX IF NOT EXISTS ix_knowledge_tenant_lifecycle ON knowledge(tenant_id, lifecycle_state);"
        ]

        for idx_q in index_queries:
            try:
                conn.execute(text(idx_q))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Notice on index query '{idx_q}': {e}")

        print("KOSH Knowledge Lifecycle schema migration completed successfully.")


if __name__ == "__main__":
    migrate_knowledge_lifecycle_schema()
