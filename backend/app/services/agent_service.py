from app.services.kosh_service import kosh
from agents.graph import brahma_app


def run_agent(task):
    print("================================")
    print("RUN_AGENT CALLED")
    print("TASK ID =", task.id)
    print("================================")

    # Derive authoritative tenant_id from task / user context (Whitesheet §18.5, CA-008)
    tenant_id = getattr(task, "tenant_id", None)
    if not tenant_id and getattr(task, "user_id", None):
        tenant_id = f"tenant_{task.user_id}"

    if not tenant_id or not str(tenant_id).strip():
        raise ValueError(f"Security Violation: Cannot run task {task.id} without valid tenant identity (CA-008 fail-closed).")

    clean_tenant_id = str(tenant_id).strip()

    knowledge = kosh.retrieve(
        query=task.prompt,
        tenant_id=clean_tenant_id,
        user_id=getattr(task, "user_id", None)
    )

    state = {
        "task_id": str(task.id),
        "trace_id": f"task-{task.id}",
        "tenant_id": clean_tenant_id,
        "user_id": getattr(task, "user_id", None),
        "intent": task.prompt,
        "knowledge": knowledge,
        "errors": [],
    }

    result = brahma_app.invoke(state)

    return result