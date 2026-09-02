from app.services.kosh_service import kosh
from agents.graph import brahma_app


def run_agent(task):
    print("================================")
    print("RUN_AGENT CALLED")
    print("TASK ID =", task.id)
    print("================================")

    knowledge = kosh.retrieve(task.prompt)

    state = {
        "task_id": str(task.id),
        "trace_id": f"task-{task.id}",
        "intent": task.prompt,
        "knowledge": knowledge,
        "errors": [],
    }

    result = brahma_app.invoke(state)

    return result