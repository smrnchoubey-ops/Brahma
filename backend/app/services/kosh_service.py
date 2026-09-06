from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.repositories.knowledge_repository import semantic_search


class KoshService:

    def retrieve(self, query: str, user_id: Optional[int] = None, top_k: int = 3) -> List[Dict[str, Any]]:
        db: Session = SessionLocal()
        try:
            return semantic_search(db, query, user_id=user_id, top_k=top_k)
        finally:
            db.close()


kosh = KoshService()