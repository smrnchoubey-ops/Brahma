from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.repositories.knowledge_repository import semantic_search


class KoshService:

    def retrieve(self, query: str):

        db: Session = SessionLocal()

        try:
            return semantic_search(db, query)
        finally:
            db.close()


kosh = KoshService()