from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.audit import AuditCreate
from app.services.audit_service import audit_service

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.post("/")
def create_log(log: AuditCreate, db: Session = Depends(get_db)):
    return audit_service.create(
        db,
        log.task_id,
        log.agent,
        log.action
    )


@router.get("/")
def get_logs(db: Session = Depends(get_db)):
    return audit_service.get_all(db)