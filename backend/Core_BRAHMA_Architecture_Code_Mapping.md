# Core BRAHMA Architecture Code Mapping

| Architecture Component | Python Module / File | Function / Class | Node / Processing | Input / Next Node | DB / API Integration |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **API Entry Point** | `backend/main.py` | `create_task()`, `get_task()` | N/A | REST Request -> FastAPI Route | PostgreSQL (Read/Write via SQLAlchemy) |
| **LangGraph Builder** | `backend/agents/graph.py` | `build_graph()` | Configures Edges & Nodes | `Task` -> Start Node | N/A |
| **KARMA** | `backend/agents/nodes/karma.py` | `karma_node()` | Orchestrator/Intent Parsing | `User Task` -> `KOSH` | N/A |
| **KOSH** | `backend/agents/nodes/kosh.py` | `kosh_node()` | pgvector Context Retrieval | `Intent` -> `PRAGYA` | pgvector (Semantic Search) |
| **SMRITI** | N/A | N/A | CONCEPTUAL / NOT IMPLEMENTED | N/A | N/A |
| **PRAGYA** | `backend/agents/nodes/pragya.py` | `pragya_node()` | Generates Structured Plan | `Context + Intent` -> `MURPHY` | LiteLLM |
| **MURPHY** | `backend/agents/nodes/murphy.py` | `murphy_node()` | Risk Analysis | `Plan` -> `MARYADA` | LiteLLM |
| **MARYADA** | `backend/agents/nodes/maryada.py`| `maryada_node()` | Governance & Policy Gate | `Risk Report` -> `RACHIT` | LiteLLM |
| **RACHIT** | `backend/agents/nodes/rachit.py` | `rachit_node()` | Executor Simulation | `Approved Policy` -> `End` | DB persistence |
| **NIYANTRA** | N/A | N/A | CONCEPTUAL / NOT IMPLEMENTED | N/A | N/A |
| **LISA** | N/A | N/A | CONCEPTUAL / NOT IMPLEMENTED | N/A | N/A |
| **Audit Service** | `backend/app/services/audit.py`| `log_audit_event()` | Synchronous Ledgering | Any Node state change | `AuditEvent` table |
| **LLM Router** | `backend/app/core/llm.py` | `call_llm()`, `get_llm_config()` | Centralized LiteLLM Router | Any LangGraph Node request | OpenRouter / Ollama API |
| **Authentication** | `backend/app/api/auth.py` | `login()`, `create_access_token()` | JWT issuance | REST Request | SQLite (Users mock) |
