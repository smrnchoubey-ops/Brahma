from sqlalchemy import Column, Integer, String, DateTime, JSON, ForeignKey
from sqlalchemy.sql import func
from app.db.database import Base



class Task(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    title = Column(String(255), nullable=False)
    prompt = Column(String, nullable=False)

    status = Column(
        String(50),
        nullable=False,
        default="PENDING"
    )

    mode = Column(
        String(50),
        nullable=False,
        default="REACTIVE"
    )

    risk_level = Column(
        String(20),
        default="LOW"
    )

    plan = Column(
        JSON,
        nullable=True
    )

    risk_report = Column(
        JSON,
        nullable=True
    )

    policy_verdict = Column(
        JSON,
        nullable=True
    )

    execution_result = Column(
    JSON,
    nullable=True
)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now()
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now()
    )