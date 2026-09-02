# BRAHMA COS Documentation (As-Built)

## 1. Introduction
- **What is BRAHMA COS?**: BRAHMA COS is a specialized agentic workflow system designed to evaluate tasks via reasoning, analyze associated risks, and apply strict governance policies before any execution occurs.
- **Purpose**: To provide a secure, auditable, and fail-closed orchestration engine for LLM-driven autonomous agents, ensuring that no action is taken without explicit risk assessment and policy approval.
- **Objectives**: Route user intents through a verifiable pipeline of intelligent agents (KARMA $\rightarrow$ KOSH $\rightarrow$ PRAGYA $\rightarrow$ MURPHY $\rightarrow$ MARYADA) before actuation (RACHIT).
- **Current Scope**: The system currently functions as a reasoning and governance engine. Actuation (execution of plans) is currently stubbed out, and advanced memory/analytics are conceptual.

## 2. Architecture
- **High-level architecture**: A pipeline of highly specialized, modular agents orchestrated as a directed graph.
- **Technology stack**: Python 3.10+, FastAPI, LangGraph, LiteLLM, PostgreSQL (`pgvector`), Argon2 (via passlib).
- **Backend architecture**: REST API built with FastAPI, using Uvicorn as an ASGI server. Background tasks execute the agent workflow asynchronously to prevent blocking the HTTP requests.
- **LangGraph architecture**: A `StateGraph` passing a strictly typed `AgentState` dictionary between nodes.
- **Database architecture**: PostgreSQL storing users, tasks, and an application-level append-only audit ledger (`audit_logs`). Includes `pgvector` for semantic search (KOSH).
- **LLM architecture**: LiteLLM acts as a gateway to OpenRouter, currently invoking `openai/gpt-oss-20b`.
- **API architecture**: Standard RESTful endpoints (`/tasks`, `/auth/login`, `/api/audit`) with JWT Bearer authentication.

## 3. Agent Documentation

### KARMA
- **Purpose**: Task intake, intent analysis, and security scanning.
- **Actual implementation**: Parses raw intent, scans for prompt injection heuristics (e.g., "ignore previous instructions"), and short-circuits the request by failing closed if malicious. It does NOT sanitize or strip the payload.
- **Input**: Raw user string `intent`.
- **Output**: Generates initial `AgentState`, sets `current_agent: KARMA`.
- **Dependencies**: Regex-based heuristic filters.
- **Connections**: Passes state to KOSH.
- **Current status**: **IMPLEMENTED & VERIFIED**

### KOSH
- **Purpose**: Context retrieval and knowledge aggregation.
- **Actual implementation**: Connects to `pgvector` to semantically search for knowledge relevant to the intent.
- **Input**: `intent`.
- **Output**: `knowledge_context` string.
- **Dependencies**: PostgreSQL (`pgvector`).
- **Connections**: Precedes PRAGYA. Skips execution if upstream failed.
- **Current status**: **IMPLEMENTED & VERIFIED** (Database contains populated knowledge records, e.g., 'Project Phoenix Guidelines' and 'Employee Policy').

### PRAGYA
- **Purpose**: Core reasoning and planning.
- **Actual implementation**: Formulates a structured step-by-step plan using the `PragyaPlan` Pydantic schema.
- **Input**: `intent` and `knowledge_context`.
- **Output**: Structured JSON plan dumped to state.
- **Dependencies**: LiteLLM, OpenRouter.
- **Connections**: Precedes MURPHY. Skips execution if upstream failed.
- **Current status**: **IMPLEMENTED & VERIFIED**

### MURPHY
- **Purpose**: Red-teaming and risk analysis.
- **Actual implementation**: Evaluates PRAGYA's plan for edge cases, security risks, and failures, outputting a `MurphyRiskReport` (LOW, MEDIUM, HIGH, CRITICAL).
- **Input**: PRAGYA's `plan`.
- **Output**: Structured JSON risk report.
- **Dependencies**: LiteLLM, OpenRouter.
- **Connections**: Precedes MARYADA. Skips if PRAGYA skipped/failed.
- **Current status**: **IMPLEMENTED & VERIFIED**

### MARYADA
- **Purpose**: Policy governance and authorization.
- **Actual implementation**: Evaluates the plan and risk report against enterprise policies. Deterministically fails closed (`MARYADA_BLOCKED`) if any upstream errors are detected, if upstream components failed (e.g., PRAGYA, MURPHY), on system errors, or if the risk is HIGH/CRITICAL. MEDIUM risk enforces HUMAN_REVIEW.
- **Input**: `intent`, `plan`, `risk_report`, upstream `errors`.
- **Output**: `PolicyVerdict` JSON and routing decision.
- **Dependencies**: LiteLLM, OpenRouter.
- **Connections**: Routes to RACHIT if APPROVED, otherwise END.
- **Current status**: **IMPLEMENTED & VERIFIED**

### RACHIT
- **Purpose**: Actuation and execution of approved plans.
- **Actual implementation**: A stubbed node that returns a generic success message. Does not execute arbitrary scripts.
- **Input**: `plan` (if APPROVED).
- **Output**: `execution_result`.
- **Dependencies**: None currently.
- **Connections**: Terminal node.
- **Current status**: **PARTIALLY IMPLEMENTED** (Execution sandbox is missing).

### SMRITI
- **Purpose**: Persistent memory and state management across sessions.
- **Actual implementation**: API endpoints exist, but it is not physically wired into the active LangGraph routing.
- **Current status**: **PARTIALLY IMPLEMENTED**

### NIYANTRA
- **Purpose**: Control plane and global monitoring.
- **Actual implementation**: Not a physical graph node. It exists conceptually as the `app.services.audit_service` which logs agent actions to the database.
- **Current status**: **CONCEPTUAL / STUBBED**

### LISA
- **Purpose**: Analytics and notifications.
- **Actual implementation**: Not present in the codebase.
- **Current status**: **NOT IMPLEMENTED**

## 4. LangGraph Workflow

The workflow relies on a `StateGraph` that passes an `AgentState` TypedDict containing `intent`, `plan`, `risk_report`, `policy_verdict`, `errors`, and `status`.

**Graph Edges:**
KARMA $\rightarrow$ KOSH $\rightarrow$ PRAGYA $\rightarrow$ MURPHY $\rightarrow$ MARYADA $\rightarrow$ Conditional Routing

**Conditional Routing (`route_after_maryada`):**
- If `status == "MARYADA_APPROVED"`: Route to RACHIT.
- Else (BLOCKED/FAILED/HUMAN_REVIEW): Route to END.

*Note: All downstream nodes check upstream `status` and `errors`. If KARMA detects an attack, it logs `KARMA_FAILED`, causing all subsequent nodes to skip execution until MARYADA deterministically fails closed.*

## 5. End-to-End Request Lifecycle

1. **User** submits `POST /tasks/` with an `intent` string.
2. **FastAPI** intercepts the request.
3. **Authentication**: Validates JWT token via `Depends(get_current_user)`.
4. Checks idempotency (blocks duplicates within 5 minutes).
5. Spawns `run_agent_workflow` as a background task.
6. **KARMA** extracts intent and runs a prompt-injection security heuristic.
7. **KOSH** attempts vector DB retrieval for context.
8. **PRAGYA** queries LLM to generate a structured execution plan.
9. **MURPHY** analyzes the plan for risks via LLM.
10. **MARYADA** checks risk tier and approves or blocks.
11. **RACHIT / END**: If approved, RACHIT stubs execution. The final database task is marked COMPLETED, BLOCKED, FAILED, or HUMAN_REVIEW based on the terminal state.

## 6. Security

- **JWT authentication**: Standard OAuth2 Password Bearer implementation. Routes are strictly protected.
- **Password hashing**: Utilizes `argon2` via `passlib` for robust defense against brute-force attacks.
- **Prompt injection protection**: Heuristic matching in KARMA rejects and short-circuits adversarial payloads before LLM execution.
- **KARMA security checks**: Traps payloads containing "ignore previous instructions", "override", etc.
- **MARYADA governance**: Enforces strict security semantics (e.g., overrides LLM approvals if MURPHY reported HIGH risk).
- **Fail-closed behaviour**: If any LLM fails, timeouts occur, or malicious intent is found, MARYADA deterministically fails closed.
- **Audit logging**: `app.services.audit_service` writes append-only application logs to the `audit_logs` table for workflow events.

## 7. LLM Layer

- **LiteLLM**: Used as the unified completion gateway (`call_llm`).
- **OpenRouter**: The primary inference provider endpoint.
- **Current model**: `openai/gpt-oss-20b` (configured via `.env`).
- **Retry behaviour**: Configured for exponential backoff (max 3 retries).
- **Failure handling**: If all retries fail, an exception is caught, appending to `errors` and triggering a fail-closed response in the graph.

## 8. Knowledge & Memory

- **PostgreSQL**: The primary relational data store.
- **pgvector**: Enabled in Postgres for semantic similarity search.
- **KOSH**: Queries `pgvector` based on user intent. Returns empty gracefully if no context is found.
- **SMRITI**: Conceptual long-term memory layer, not fully integrated.
- **Current limitations**: The vector database requires an ingestion pipeline to populate knowledge before KOSH can return meaningful data.

## 9. Execution Layer

**RACHIT is currently PARTIALLY IMPLEMENTED.**
The current RACHIT implementation is a stub. It intercepts approved plans and immediately returns a dummy "Execution completed successfully" message. It does **not** yet provide a production-grade execution sandbox (e.g., Docker-in-Docker or isolated Python runtimes). True execution capabilities remain blocked pending infrastructure upgrades.

## 10. Testing

The following tests were actively executed via `verify_all.py` against the running Uvicorn server:
Command: `python verify_all.py`
Evidence Location: Terminal output log (task-134.log)

- **Missing JWT**:
  - Actual result: Status Code: 401
  - Status: VERIFIED
- **Invalid JWT**: 
  - Actual result: Status Code: 401
  - Status: VERIFIED
- **Benign workflow**: 
  - Actual result: COMPLETED
  - Status: VERIFIED
- **Prompt injection**: 
  - Actual result: FAILED/BLOCKED
  - Status: VERIFIED

## 11. Capability Matrix

| Capability | Status | Evidence |
| :--- | :--- | :--- |
| Core Agent Workflow | IMPLEMENTED & VERIFIED | End-to-end task completion logs |
| Structured LLM Outputs | IMPLEMENTED & VERIFIED | Pydantic schema validation traces |
| Deterministic Fail-Closed | IMPLEMENTED & VERIFIED | Upstream failure trapping in Maryada |
| Prompt Injection Protection | IMPLEMENTED & VERIFIED | Test 2: Prompt Injection -> FAILED |
| Immutable Audit Ledger | IMPLEMENTED & VERIFIED | `api/audit` populated during runs |
| Vector Knowledge (RAG) | IMPLEMENTED | DB connections succeed, gracefully returns empty |
| Execution Sandbox | PARTIALLY IMPLEMENTED | RACHIT exists as a stub node only |
| LLM Fallback Pool | OPEN/BLOCKED | Secondary credentials unavailable |

## 12. Threat Model

- **Prompt injection**: Mitigated via heuristic scanning in KARMA and strict Pydantic schemas in downstream nodes.
- **LLM failure**: Mitigated via LiteLLM retries and deterministic graph fail-closed policies.
- **Authentication risks**: Mitigated via Argon2 hashing and configured JWTs (60 minutes default).
- **DoS considerations**: Mitigated via strict 5-minute idempotency caching on the `/tasks` API.
- **Execution/RCE risks**: Acknowledged. Actual execution is deferred until Gap 3 (RACHIT Sandbox) is implemented.

## 13. Phase 5 Gap Analysis

- **Gap 1 — LLM Fallback Pool**: Status: **BLOCKED — SECONDARY PROVIDER CREDENTIALS NOT AVAILABLE**
- **Gap 2 — Prompt Injection Protection**: Status: **CLOSED**
- **Gap 3 — RACHIT Execution Sandbox**: Status: **OPEN**

## 14. Future Roadmap

- **LLM fallback**: Implement primary/secondary provider routing once credentials are provisioned.
- **RACHIT sandbox**: Deploy isolated container runtimes for safe actuation.
- **Memory integration**: Fully wire SMRITI into the graph for cross-session context.
- **LISA**: Introduce human-in-the-loop notification and analytics portals.
- **Advanced governance**: Introduce dynamic policy ingestion from enterprise systems.
- **Monitoring**: Datadog/Prometheus integration for graph execution metrics.
- **Production hardening**: Transition from Uvicorn `--reload` to production Gunicorn workers.
