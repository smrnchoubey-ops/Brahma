"""
Migration script for Learning Patterns schema (F14/F15 - Gap #2).
Creates PostgreSQL table 'learning_patterns' to persist F14/F15 learning candidates
and pattern lifecycles across process restarts.
Strictly enforces NOT NULL on tenant_id with NO default.
"""
import os
import sys

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy import text
from app.db.database import engine


def migrate_learning_patterns_schema():
    with engine.connect() as conn:
        print("Starting Learning Patterns schema migration on PostgreSQL...")

        # 1. Create learning_patterns table if not exists
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS learning_patterns (
                id SERIAL PRIMARY KEY,
                pattern_id VARCHAR(128) NOT NULL UNIQUE,
                tenant_id VARCHAR(64) NOT NULL,
                pattern_type VARCHAR(64) NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'CANDIDATE',
                fingerprint VARCHAR(128),
                confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
                version INTEGER NOT NULL DEFAULT 1,
                le_score DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                constitutional_approved BOOLEAN NOT NULL DEFAULT FALSE,
                shadow_passed BOOLEAN NOT NULL DEFAULT FALSE,
                regression_passed BOOLEAN NOT NULL DEFAULT FALSE,
                action_template JSONB NOT NULL DEFAULT '{}'::jsonb,
                evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
                source_episode_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                metadata_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                promoted_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """))
        conn.commit()

        # 2. Add any missing columns or adjust column types to existing table if previously partially created
        alter_queries = [
            "ALTER TABLE learning_patterns ALTER COLUMN fingerprint TYPE VARCHAR(128);",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS pattern_id VARCHAR(128) NOT NULL UNIQUE;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64) NOT NULL;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS pattern_type VARCHAR(64) NOT NULL;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS name VARCHAR(255) NOT NULL;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS description TEXT NOT NULL;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'CANDIDATE';",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS fingerprint VARCHAR(128);",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS le_score DOUBLE PRECISION NOT NULL DEFAULT 0.0;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS constitutional_approved BOOLEAN NOT NULL DEFAULT FALSE;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS shadow_passed BOOLEAN NOT NULL DEFAULT FALSE;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS regression_passed BOOLEAN NOT NULL DEFAULT FALSE;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS action_template JSONB NOT NULL DEFAULT '{}'::jsonb;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS evidence JSONB NOT NULL DEFAULT '{}'::jsonb;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS source_episode_ids JSONB NOT NULL DEFAULT '[]'::jsonb;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS metadata_payload JSONB NOT NULL DEFAULT '{}'::jsonb;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS promoted_at TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE learning_patterns ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;"
        ]

        for q in alter_queries:
            try:
                conn.execute(text(q))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Notice on query '{q}': {e}")

        # 3. Create indices for tenant-scoped querying, pattern lookup, and status filtering
        index_queries = [
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_learning_patterns_pattern_id ON learning_patterns(pattern_id);",
            "CREATE INDEX IF NOT EXISTS ix_learning_patterns_tenant_id ON learning_patterns(tenant_id);",
            "CREATE INDEX IF NOT EXISTS ix_learning_patterns_status ON learning_patterns(status);",
            "CREATE INDEX IF NOT EXISTS ix_learning_patterns_pattern_type ON learning_patterns(pattern_type);",
            "CREATE INDEX IF NOT EXISTS ix_learning_patterns_fingerprint ON learning_patterns(fingerprint);",
            "CREATE INDEX IF NOT EXISTS ix_learning_patterns_created_at ON learning_patterns(created_at);",
            "CREATE INDEX IF NOT EXISTS ix_learning_patterns_tenant_status ON learning_patterns(tenant_id, status);"
        ]

        for idx_q in index_queries:
            try:
                conn.execute(text(idx_q))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Notice on index query '{idx_q}': {e}")

        print("Learning Patterns schema migration completed successfully.")


if __name__ == "__main__":
    migrate_learning_patterns_schema()
