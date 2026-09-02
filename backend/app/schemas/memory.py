from pydantic import BaseModel
from datetime import datetime


class MemoryCreate(BaseModel):
    content: str
    source: str = "user"


class MemoryResponse(BaseModel):
    id: int
    content: str
    source: str
    approved: str
    created_at: datetime

    class Config:
        from_attributes = True