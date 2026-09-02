from sqlalchemy.orm import Session

from app.models.task import Task
from app.schemas.task import TaskCreate
from app.services.agent_service import run_agent


def create_task(db: Session, task: TaskCreate):

    # Create initial task
    db_task = Task(
        title=task.title,
        prompt=task.prompt,
        status="PENDING",
        risk_level="LOW"
    )

    db.add(db_task)
    db.commit()
    db.refresh(db_task)

    try:
        # Update status
        db_task.status = "RUNNING"
        db.commit()

        print("Before run_agent")

        # Run BRAHMA pipeline
        result = run_agent(db_task)

        print("After run_agent")

        # --------------------------
        # Save PRAGYA Plan
        # --------------------------
        if result.get("plan"):
            db_task.plan = result["plan"]

        # --------------------------
        # Save MURPHY Risk Report
        # --------------------------
        if result.get("risk_report"):
            db_task.risk_report = result["risk_report"]

        # --------------------------
        # Save MARYADA Policy Verdict
        # --------------------------
        if result.get("policy_verdict"):
            db_task.policy_verdict = result["policy_verdict"]

        # --------------------------
        # Save RACHIT Execution Result
        # --------------------------
        if result.get("execution_result"):
            db_task.execution_result = result["execution_result"]

        # --------------------------
        # Final Status
        # --------------------------
        verdict = result.get("policy_verdict")

        if verdict:

            db_task.risk_level = verdict.get(
                "risk_tier",
                "LOW"
            )

            if verdict.get("approved"):
                db_task.status = "COMPLETED"
            else:
                db_task.status = "BLOCKED"

        else:
            db_task.status = "COMPLETED"

    except Exception as e:

        db_task.status = "FAILED"
        print("Agent Error:", e)

    db.commit()
    db.refresh(db_task)

    return db_task


def get_all_tasks(db: Session):
    return db.query(Task).all()


def update_task_status(
    db: Session,
    task_id: int,
    status: str,
):
    task = db.query(Task).filter(Task.id == task_id).first()

    if task:
        task.status = status
        db.commit()
        db.refresh(task)

    return task


def save_plan(
    db: Session,
    task_id: int,
    plan: dict,
):
    task = db.query(Task).filter(Task.id == task_id).first()

    if task:
        task.plan = plan
        db.commit()
        db.refresh(task)

    return task


def save_risk(
    db: Session,
    task_id: int,
    risk: dict,
):
    task = db.query(Task).filter(Task.id == task_id).first()

    if task:
        task.risk_report = risk
        task.risk_level = risk.get("risk_level", "LOW")
        db.commit()
        db.refresh(task)

    return task


def save_policy(
    db: Session,
    task_id: int,
    verdict: dict,
):
    task = db.query(Task).filter(Task.id == task_id).first()

    if task:
        task.policy_verdict = verdict
        task.risk_level = verdict.get(
            "risk_tier",
            task.risk_level
        )
        db.commit()
        db.refresh(task)

    return task


def save_execution(
    db: Session,
    task_id: int,
    execution: dict,
):
    task = db.query(Task).filter(Task.id == task_id).first()

    if task:
        task.execution_result = execution
        db.commit()
        db.refresh(task)

    return task