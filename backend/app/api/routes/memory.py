from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.memory import MemoryCreate
from app.services.memory_service import memory_service

router = APIRouter(prefix="/memory", tags=["Memory"])


@router.post("/")
def create_memory(memory: MemoryCreate, db: Session = Depends(get_db)):
    return memory_service.create(
        db,
        memory.content,
        memory.source
    )


@router.get("/")
def get_memories(db: Session = Depends(get_db)):
    return memory_service.get_all(db)


@router.put("/{memory_id}/approve")
def approve_memory(memory_id: int, db: Session = Depends(get_db)):
    return memory_service.approve(db, memory_id)


@router.delete("/{memory_id}")
def delete_memory(memory_id: int, db: Session = Depends(get_db)):
    return memory_service.delete(db, memory_id)