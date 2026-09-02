from pydantic import BaseModel
from datetime import datetime
from typing import Any


class TaskCreate(BaseModel):
    title: str
    prompt: str


class TaskResponse(BaseModel):
    id: int
    title: str
    prompt: str

    status: str
    risk_level: str

    plan: dict[str, Any] | None = None
    risk_report: dict[str, Any] | None = None
    policy_verdict: dict[str, Any] | None = None
    execution_result: dict[str, Any] | None = None

    created_at: datetime

    class Config:
        from_attributes = True