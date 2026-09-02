from sqlalchemy.orm import Session

from app.repositories.audit_repository import audit_repository


class AuditService:

    def create(self, db: Session, task_id: int, agent: str, event_type: str, status: str = "SUCCESS", payload_snapshot: dict = None):
        return audit_repository.create(db, task_id, agent, event_type, status, payload_snapshot)

    def get_all(self, db: Session):
        return audit_repository.get_all(db)


audit_service = AuditService()

from app.db.database import SessionLocal

def log_audit_event(task_id: int, agent: str, event_type: str, status: str = "SUCCESS", payload_snapshot: dict = None):
    db = SessionLocal()
    try:
        audit_service.create(db, task_id, agent, event_type, status, payload_snapshot)
    except Exception as e:
        print(f"Audit log failed: {e}")
    finally:
        db.close()