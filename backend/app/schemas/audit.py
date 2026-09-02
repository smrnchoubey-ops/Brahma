from pydantic import BaseModel
from datetime import datetime


class AuditCreate(BaseModel):
    task_id: int
    agent: str
    action: str


class AuditResponse(BaseModel):
    id: int
    task_id: int
    agent: str
    action: str
    created_at: datetime

    class Config:
        from_attributes = True