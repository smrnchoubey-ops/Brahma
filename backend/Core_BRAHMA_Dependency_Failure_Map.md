# Core BRAHMA Dependency Failure Map

| Component / Dependency | Failure Mode | Expected Behavior | Retry / Fallback | Final State | Audit Event |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **OpenRouter / LiteLLM API** | Network Timeout / `404 Not Found` | Agent throws exception gracefully | Default `litellm` retries exhausted | FAILED | PRAGYA_FAILED / MURPHY_FAILED |
| **Ollama Local LLM** | Truncated Tokens / EOF Schema | `pydantic` JSON validation fails | System Fail Closed | BLOCKED | MARYADA_BLOCKED |
| **PostgreSQL Database** | Connection Refused | Application failure at boot | Dependent on Docker restart policies | SYSTEM OFFLINE | N/A |
| **pgvector Engine** | Vector embedding dimension mismatch | Semantic search fails gracefully returning empty array | No retries | SUCCESS (No Context) | KOSH_RETRIEVAL_FAILED (warning) |
| **Authentication Service** | Expired JWT | 401 Unauthorized API error | None | DENIED | Auth exception |
| **KARMA Orchestrator** | Intent parsing exception | Halts LangGraph pipeline | No retries | FAILED | KARMA_FAILED |
| **PRAGYA Node** | Reasoning LLM failure | State logs `PRAGYA_FAILED` | No retries | BLOCKED (via MARYADA fallback) | PRAGYA_FAILED -> MARYADA_BLOCKED |
| **MURPHY Node** | Risk Analysis LLM failure | State logs `MURPHY_FAILED`, Risk assigned `UNKNOWN` | No retries | BLOCKED (via MARYADA fallback) | MURPHY_FAILED -> MARYADA_BLOCKED |
| **MARYADA Node** | Invalid Policy LLM Output | Falls back to default `BLOCKED` policy object | No retries | BLOCKED | MARYADA_BLOCKED |
| **RACHIT Executor** | Execution failure post-approval | State logs execution error traceback | None | FAILED | RACHIT_FAILED |
