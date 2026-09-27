from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.repositories.knowledge_repository import semantic_search


class KoshService:
    """
    KOSH Retrieval Service wrapper around knowledge repository.
    Enforces mandatory tenant_id parameter fail-closed (CA-008, Whitesheet §18.5).
    """

    def retrieve(
        self,
        query: str,
        tenant_id: str,
        user_id: Optional[int] = None,
        top_k: int = 3
    ) -> List[Dict[str, Any]]:
        if not tenant_id or not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ValueError("Security Violation: KOSH retrieve requires a valid non-empty tenant_id (CA-008 fail-closed).")

        db: Session = SessionLocal()
        try:
            return semantic_search(
                db=db,
                query=query,
                tenant_id=tenant_id.strip(),
                user_id=user_id,
                top_k=top_k
            )
        finally:
            db.close()


kosh = KoshService()