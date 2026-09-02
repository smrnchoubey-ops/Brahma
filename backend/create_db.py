from sqlalchemy import text
from app.db.database import Base, engine
from app.models.task import Task
from app.models.knowledge import Knowledge
from app.models.audit_event import AuditEvent
from app.models.user import User

with engine.connect() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
    conn.commit()

Base.metadata.create_all(bind=engine)

print("Database tables created successfully.")