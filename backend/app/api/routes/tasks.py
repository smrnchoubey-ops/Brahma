from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.task import TaskCreate, TaskResponse

from app.repositories.task_repository import (
    create_task,
    get_all_tasks,
)

router = APIRouter(
    prefix="/tasks",
    tags=["Tasks"],
)


@router.post("/", response_model=TaskResponse)
def add_task(
    task: TaskCreate,
    db: Session = Depends(get_db),
):
    return create_task(db, task)


@router.get("/", response_model=list[TaskResponse])
def read_tasks(
    db: Session = Depends(get_db),
):
    return get_all_tasks(db)