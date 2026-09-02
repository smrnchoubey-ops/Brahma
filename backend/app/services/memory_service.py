from sqlalchemy.orm import Session

from app.repositories.memory_repository import memory_repository


class MemoryService:

    def create(self, db: Session, content: str, source: str):
        return memory_repository.create(db, content, source)

    def get_all(self, db: Session):
        return memory_repository.get_all(db)

    def approve(self, db: Session, memory_id: int):
        return memory_repository.approve(db, memory_id)

    def delete(self, db: Session, memory_id: int):
        return memory_repository.delete(db, memory_id)


memory_service = MemoryService()