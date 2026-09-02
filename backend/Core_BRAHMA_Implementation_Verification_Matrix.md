# Core BRAHMA Implementation & Verification Matrix

| Component | Status | Evidence/Notes |
| :--- | :--- | :--- |
| **KARMA** | IMPLEMENTED & VERIFIED | Parses user intent, stores in state, and correctly activates PRAGYA/KOSH. Tested via `test_kosh_integration.py`. |
| **KOSH** | IMPLEMENTED & VERIFIED | LangGraph node successfully queries `pgvector` index via `semantic_search()` and passes context to PRAGYA. |
| **SMRITI** | CONCEPTUAL / PLANNED | No implementation found. Architecture placeholders exist. |
| **PRAGYA** | IMPLEMENTED & VERIFIED | Receives intent and KOSH context, reasons properly, and emits strict JSON using explicit LLM parameters. |
| **MURPHY** | IMPLEMENTED & VERIFIED | Analyzes risk, effectively failing closed (UNKNOWN) upon LLM failures or invalid structured outputs. |
| **MARYADA** | IMPLEMENTED & VERIFIED | Successfully defaults to BLOCKED on upstream failures, blocks HIGH/CRITICAL risk dynamically, and approves valid LOW risk plans. |
| **RACHIT** | IMPLEMENTED & VERIFIED | Triggers only upon MARYADA APPROVED status, proven by complete integration test run. |
| **NIYANTRA** | CONCEPTUAL / PLANNED | No implementation found. |
| **LISA** | CONCEPTUAL / PLANNED | No implementation found. |
| **PostgreSQL** | IMPLEMENTED & VERIFIED | Verified via REST checks and direct DB queries showing task row persistence via `SessionLocal`. |
| **pgvector** | IMPLEMENTED & VERIFIED | Verified via semantic search embedding matches during KOSH retrieval phase. |
| **Authentication** | IMPLEMENTED & VERIFIED | Argon2 hashed JWT flow confirmed blocking unauthorized routes. |
| **LLM** | IMPLEMENTED & VERIFIED | LiteLLM routing via Ollama/OpenRouter verified, along with strict `max_tokens` handling for stable JSON output. |
| **Audit** | IMPLEMENTED & VERIFIED | End-to-end ledger of states recorded synchronously via `log_audit_event()`. |
| **Dashboard** | IMPLEMENTED & VERIFIED | React frontend verified dynamically polling `/api/metrics` and `/api/tasks`. |
