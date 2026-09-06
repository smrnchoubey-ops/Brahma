from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.embedding_service import generate_embedding


def semantic_search(db: Session, query: str, user_id: Optional[int] = None, top_k: int = 3) -> List[Dict[str, Any]]:
    embedding = generate_embedding(query)

    # Python list -> PostgreSQL vector string
    embedding_str = "[" + ",".join(map(str, embedding)) + "]"

    if user_id is not None:
        # Strictly tenant-scoped vector search
        sql = text("""
            SELECT title, content
            FROM knowledge
            WHERE user_id = :user_id OR user_id IS NULL
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """)
        params = {
            "embedding": embedding_str,
            "user_id": user_id,
            "top_k": top_k,
        }
    else:
        sql = text("""
            SELECT title, content
            FROM knowledge
            WHERE user_id IS NULL
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """)
        params = {
            "embedding": embedding_str,
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