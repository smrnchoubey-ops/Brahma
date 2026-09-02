# Core BRAHMA API Documentation

## Authentication (`/auth/login`)
**Method**: POST
**Authentication**: None
**Description**: Authenticates users and returns a JWT Bearer token.
*   **Request Form Data**: `username` (string), `password` (string)
*   **Response**: `200 OK`
    ```json
    { "access_token": "eyJhb...", "token_type": "bearer" }
    ```

## Task Submission (`/tasks/`)
**Method**: POST
**Authentication**: JWT Bearer
**Description**: Submits a natural language task request to the BRAHMA COS orchestration graph.
*   **Request Schema**:
    ```json
    { "prompt": "String containing execution intent" }
    ```
*   **Response**: `200 OK`
    ```json
    { "task_id": 1, "status": "PENDING", "message": "Task dispatched." }
    ```

## Task Polling (`/tasks/{task_id}`)
**Method**: GET
**Authentication**: JWT Bearer
**Description**: Polls the specific task to retrieve execution status and final payloads.
*   **Response**: `200 OK`
    ```json
    {
      "id": 1,
      "prompt": "...",
      "status": "COMPLETED | BLOCKED | FAILED",
      "plan": { ... },
      "risk_report": { ... },
      "policy_verdict": { ... },
      "execution_result": "Simulated successful execution of the task."
    }
    ```

## Dashboard Metrics (`/api/metrics`)
**Method**: GET
**Authentication**: JWT Bearer
**Description**: Returns real-time aggregate execution data from the PostgreSQL task datastore.
*   **Response**: `200 OK`
    ```json
    { "total_tasks": 10, "completed": 5, "blocked": 3, "failed": 2, "pending": 0 }
    ```

## Audit Ledger (`/api/audit`)
**Method**: GET
**Authentication**: JWT Bearer
**Description**: Retrieve the chronological system-wide agent activity log.
*   **Response**: `200 OK` (Array of objects)
    ```json
    [
      { "task_id": 1, "agent_name": "KARMA", "event_type": "Task Submitted", "status": "PENDING", "timestamp": "2026-08-28T00:00:00Z" }
    ]
    ```
