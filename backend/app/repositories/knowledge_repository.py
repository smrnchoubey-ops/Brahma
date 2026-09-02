from sqlalchemy.orm import Session
from sqlalchemy import text

from app.services.embedding_service import generate_embedding


def semantic_search(db: Session, query: str, top_k: int = 3):

    embedding = generate_embedding(query)

    # Python list -> PostgreSQL vector string
    embedding_str = "[" + ",".join(map(str, embedding)) + "]"

    sql = text("""
        SELECT title, content
        FROM knowledge
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT :top_k
    """)

    result = db.execute(
        sql,
        {
            "embedding": embedding_str,
            "top_k": top_k,
        },
    )

    rows = result.fetchall()

    return [
        {
            "title": row.title,
            "content": row.content,
        }
        for row in rows
    ]