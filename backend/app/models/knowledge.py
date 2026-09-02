from sqlalchemy import Column, Integer, String, Text

from pgvector.sqlalchemy import Vector

from app.db.database import Base


class Knowledge(Base):

    __tablename__ = "knowledge"

    id = Column(Integer, primary_key=True)

    title = Column(String(255))

    content = Column(Text)

    embedding = Column(Vector(768))