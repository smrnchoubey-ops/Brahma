from sqlalchemy.orm import Session
from app.models.audit import Audit


class AuditRepository:

    def create(self, db: Session, task_id: int, agent: str, event_type: str, status: str = "SUCCESS", payload_snapshot: dict = None):

        audit = Audit(
            task_id=task_id,
            agent=agent,
            event_type=event_type,
            status=status,
            payload_snapshot=payload_snapshot
        )

        db.add(audit)
        db.commit()
        db.refresh(audit)

        return audit

    def get_all(self, db: Session):
        return db.query(Audit).all()


audit_repository = AuditRepository()