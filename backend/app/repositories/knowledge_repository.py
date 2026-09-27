from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.embedding_service import generate_embedding


def semantic_search(
    db: Session,
    query: str,
    tenant_id: str,
    user_id: Optional[int] = None,
    top_k: int = 3
) -> List[Dict[str, Any]]:
    """
    Executes tenant-isolated pgvector semantic search on the PostgreSQL knowledge table.
    Fails closed if tenant_id is missing, empty, or whitespace (CA-008, Whitesheet §18.5).
    """
    if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("Security Violation: semantic_search requires a non-empty tenant_id (CA-008 fail-closed).")

    clean_tenant = tenant_id.strip()
    embedding = generate_embedding(query)

    # Python list -> PostgreSQL vector string
    embedding_str = "[" + ",".join(map(str, embedding)) + "]"

    if user_id is not None:
        # Strictly tenant-scoped vector search with optional user filter
        sql = text("""
            SELECT title, content
            FROM knowledge
            WHERE tenant_id = :tenant_id AND (user_id = :user_id OR user_id IS NULL)
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """)
        params = {
            "embedding": embedding_str,
            "tenant_id": clean_tenant,
            "user_id": user_id,
            "top_k": top_k,
        }
    else:
        sql = text("""
            SELECT title, content
            FROM knowledge
            WHERE tenant_id = :tenant_id
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """)
        params = {
            "embedding": embedding_str,
            "tenant_id": clean_tenant,
            "top_k": top_k,
        }

    result = db.execute(sql, params)
    rows = result.fetchall()

    return [
        {
            "title": row.title,
            "content": row.content,
        }
        for row in rows
    ]