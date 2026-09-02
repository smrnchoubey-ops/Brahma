# Core BRAHMA Technical Risk Register

| Risk | Severity | Probability | Impact | Status | Owner | Mitigation | Target Resolution | Closure Criteria |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| LLM JSON Schema Parsing Failures | High | High | Fails entire task workflow | MITIGATED | Antigravity | Passed rigid prompt constraints & `max_tokens` configuration in LiteLLM config | Implemented | 100% of LLM calls output valid parseable JSON schema |
| API Provider Rate Limits (OpenRouter) | High | High | System offline / unusable | OPEN | Admin | Transition entirely to Local Ollama via `LLM_PROVIDER=ollama` environment variable | Phase 6 | System operates entirely without internet dependencies |
| Synchronous Execution Timeout | Medium | High | Client UI receives timeout disconnects before task fully resolves | MITIGATED | Antigravity | Move FastAPI endpoint processing into Starlette background task executor threads | Implemented | `/tasks` endpoint responds synchronously with a Pending `task_id` for polling |
| KOSH Missing Vector Embeddings | Medium | Low | PRAGYA generates plans using hallucinated data due to missing context | OPEN | Engineers | Implement robust document-store sync mechanism and healthchecks | Phase 6 | Routine pgvector sync validation |
| Unauthorized Pipeline Invocation | Critical | Low | System execution subversion | CLOSED | Antigravity | Hardened JWT bearer dependency implemented | Implemented | `/tasks` block completely without valid JWT header |
