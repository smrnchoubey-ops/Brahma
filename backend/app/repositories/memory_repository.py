from sqlalchemy.orm import Session

from app.models.memory import Memory


class MemoryRepository:

    def create(self, db: Session, content: str, source: str):

        memory = Memory(
            content=content,
            source=source
        )

        db.add(memory)
        db.commit()
        db.refresh(memory)

        return memory

    def get_all(self, db: Session):

        return db.query(Memory).all()

    def approve(self, db: Session, memory_id: int):

        memory = db.query(Memory).filter(
            Memory.id == memory_id
        ).first()

        if memory:
            memory.approved = "APPROVED"
            db.commit()
            db.refresh(memory)

        return memory

    def delete(self, db: Session, memory_id: int):

        memory = db.query(Memory).filter(
            Memory.id == memory_id
        ).first()

        if memory:
            db.delete(memory)
            db.commit()

        return memory


memory_repository = MemoryRepository()