# Core BRAHMA Current State (Pre-UI Completion Inspection)

## Backend Verification (Phases 1-10 Already Completed & Passed)
*   **KARMA**: LangGraph node implemented, correctly parses intent. (`backend/agents/nodes/karma.py`)
*   **KOSH**: Fully integrated as a discrete LangGraph node. Queries `pgvector` and injects context into PRAGYA. Verified via `test_kosh_integration.py` execution. (`backend/agents/nodes/kosh.py`)
*   **PRAGYA**: Generates structured plans dynamically based on KOSH context and user intent. Resilience validated (strict JSON enforcement added via prompt constraints). (`backend/agents/nodes/pragya.py`)
*   **MURPHY**: Generates structured risk evaluations. Falls back to `UNKNOWN` on LLM failure, proving fail-closed architecture. (`backend/agents/nodes/murphy.py`)
*   **MARYADA**: Hard-blocks high risk tasks. Falls back to `BLOCKED` if upstream agents fail. (`backend/agents/nodes/maryada.py`)
*   **RACHIT**: Executes conditionally based purely on `MARYADA` approval state. Fully tested. (`backend/agents/nodes/rachit.py`)
*   **Database & Audit**: Full state lifecycle is preserved in PostgreSQL and chronological event ledgers are recorded. (`backend/app/services/audit.py`)
*   **Security/Resilience**: Handled via schema validation catching LLM truncations and failing closed, plus JWT endpoints.

## Frontend UI Verification (Phase 11-13 Pending)
*   **Live Data**: The dashboard (`frontend/src/app/page.tsx`) correctly fetches live data via `api.ts` from backend endpoints (`/tasks/`, `/api/metrics`, `/api/agents`, `/api/audit`).
*   **Dashboard Features Present**: Executive Overview, Agent Statuses, Audit Ledger, Task Operations table.
*   **Dashboard Features Missing / To Fix**:
    1.  **Task Detail View**: Clicking a task row must open a modal/detail view showing the trace (KARMA -> KOSH -> PRAGYA -> MURPHY -> MARYADA -> RACHIT).
    2.  **Knowledge Base Status**: Must clearly display KOSH status and label document upload functionality as unavailable.
    3.  **Agent Visuals**: Must visually differentiate running core agents from conceptual ones (SMRITI, NIYANTRA, LISA).

**Next Step**: Complete the Frontend UI features (Phase 11-13), then execute a full automated regression test suite (Phase 14).
