"""
Migration script for Federation Node Registry schema (Whitesheet §18 & §23 - Gap #8).
Creates PostgreSQL table 'federation_nodes' to persist Federation node registry state,
cryptographic standing, and trust tiers across process restarts.
Strictly enforces NOT NULL on tenant_id with NO default.
"""
import os
import sys

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy import text
from app.db.database import engine


def migrate_federation_registry_schema():
    with engine.connect() as conn:
        print("Starting Federation Node Registry schema migration on PostgreSQL...")

        # 1. Create federation_nodes table if not exists
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS federation_nodes (
                id SERIAL PRIMARY KEY,
                node_id VARCHAR(128) NOT NULL UNIQUE,
                tenant_id VARCHAR(64) NOT NULL,
                public_key TEXT NOT NULL,
                trust_tier VARCHAR(32) NOT NULL DEFAULT 'UNTRUSTED',
                status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
                name VARCHAR(255),
                endpoint VARCHAR(255),
                node_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """))
        conn.commit()

        # 2. Add any missing columns or adjust column types to existing table if previously partially created
        alter_queries = [
            "ALTER TABLE federation_nodes ADD COLUMN IF NOT EXISTS node_id VARCHAR(128) NOT NULL UNIQUE;",
            "ALTER TABLE federation_nodes ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64) NOT NULL;",
            "ALTER TABLE federation_nodes ADD COLUMN IF NOT EXISTS public_key TEXT NOT NULL;",
            "ALTER TABLE federation_nodes ADD COLUMN IF NOT EXISTS trust_tier VARCHAR(32) NOT NULL DEFAULT 'UNTRUSTED';",
            "ALTER TABLE federation_nodes ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE';",
            "ALTER TABLE federation_nodes ADD COLUMN IF NOT EXISTS name VARCHAR(255);",
            "ALTER TABLE federation_nodes ADD COLUMN IF NOT EXISTS endpoint VARCHAR(255);",
            "ALTER TABLE federation_nodes ADD COLUMN IF NOT EXISTS node_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;",
            "ALTER TABLE federation_nodes ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE federation_nodes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;"
        ]

        for q in alter_queries:
            try:
                conn.execute(text(q))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Notice on query '{q}': {e}")

        # 3. Create indices for tenant-scoped querying, node lookup, and status/trust filtering
        index_queries = [
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_federation_nodes_node_id ON federation_nodes(node_id);",
            "CREATE INDEX IF NOT EXISTS ix_federation_nodes_tenant_id ON federation_nodes(tenant_id);",
            "CREATE INDEX IF NOT EXISTS ix_federation_nodes_trust_tier ON federation_nodes(trust_tier);",
            "CREATE INDEX IF NOT EXISTS ix_federation_nodes_status ON federation_nodes(status);",
            "CREATE INDEX IF NOT EXISTS ix_federation_nodes_created_at ON federation_nodes(created_at);",
            "CREATE INDEX IF NOT EXISTS ix_federation_nodes_tenant_status ON federation_nodes(tenant_id, status);",
            "CREATE INDEX IF NOT EXISTS ix_federation_nodes_tenant_node ON federation_nodes(tenant_id, node_id);"
        ]

        for idx_q in index_queries:
            try:
                conn.execute(text(idx_q))
                conn.commit()
            except Exception as e:
                conn.rollback()
                print(f"Notice on index query '{idx_q}': {e}")

        print("Federation Node Registry schema migration completed successfully.")


if __name__ == "__main__":
    migrate_federation_registry_schema()
