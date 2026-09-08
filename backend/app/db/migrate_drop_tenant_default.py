"""
Migration script to remove DEFAULT 'global' from tenant_id in memory and knowledge tables (Gap #1).
Ensures strict defense-in-depth tenant isolation at the PostgreSQL database level.
Prevents direct SQL inserts from succeeding without explicit tenant_id.
"""
import os
import sys

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy import text
from app.db.database import engine


def migrate_drop_tenant_default():
    """
    Drops DEFAULT 'global' on tenant_id column for memory and knowledge tables,
    while guaranteeing NOT NULL constraint remains strictly enforced.
    Does not modify or delete any existing data rows.
    """
    with engine.connect() as conn:
        print("Starting migration: dropping DEFAULT 'global' on tenant_id for memory and knowledge tables...")
        
        alter_queries = [
            "ALTER TABLE memory ALTER COLUMN tenant_id DROP DEFAULT;",
            "ALTER TABLE memory ALTER COLUMN tenant_id SET NOT NULL;",
            "ALTER TABLE knowledge ALTER COLUMN tenant_id DROP DEFAULT;",
            "ALTER TABLE knowledge ALTER COLUMN tenant_id SET NOT NULL;"
        ]
        
        for q in alter_queries:
            try:
                conn.execute(text(q))
                conn.commit()
                print(f"Successfully executed: {q}")
            except Exception as e:
                conn.rollback()
                print(f"Failed executing query '{q}': {e}")
                raise

        print("Migration complete: memory.tenant_id and knowledge.tenant_id defaults removed.")


if __name__ == "__main__":
    migrate_drop_tenant_default()
