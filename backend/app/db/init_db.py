from app.db.database import Base, engine

# Import all models here
from app.models.task import Task
from app.models.knowledge import Knowledge
from app.models.memory import Memory
from app.models.audit import Audit

Base.metadata.create_all(bind=engine)

print("✅ Database tables created successfully.")