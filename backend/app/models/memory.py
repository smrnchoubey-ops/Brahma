from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func

from app.db.database import Base


class Memory(Base):
    __tablename__ = "memory"

    id = Column(Integer, primary_key=True, index=True)

    content = Column(Text, nullable=False)

    source = Column(String, default="user")

    approved = Column(String, default="PENDING")

    created_at = Column(DateTime(timezone=True), server_default=func.now())