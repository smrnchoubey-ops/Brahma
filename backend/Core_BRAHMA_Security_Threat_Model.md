# Core BRAHMA Security & Threat Model

| Threat | Likelihood | Impact | Current Control | Gap | Mitigation | Test | Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Prompt Injection** | High | Critical | `MARYADA` rigid JSON parsing fail-closed rules | PRAGYA can still ingest poisoned prompt data | Strict character whitelisting prior to parsing | Submitted Prompt Injection via task | Caught by MARYADA (Failed Schema) - PASS |
| **Unauthorized Execution** | Low | Critical | `RACHIT` requires `status == 'MARYADA_APPROVED'` | Direct DB manipulation | Database service level hardening | Direct API invocation of `RACHIT` | Impossible due to LangGraph architecture - PASS |
| **Authentication Bypass** | Low | High | Argon2 hashes + OAuth2 Bearer dependencies | Refresh token mechanics missing | Complete FastAPI authorization implementation | `curl` with missing headers | `401 Unauthorized` - PASS |
| **Token Leakage** | Medium | High | Expiration constraints (30 mins) | Tokens are not rotated/invalidated cleanly on sign-out | Short-lived tokens with client-side deletion | Expiration time test | PASS |
| **Retrieved-Context Poisoning** | Low | Critical | `KOSH` isolated semantic index namespace | Document upload pipeline currently unverified for malware parsing | Implement sanitization micro-service | KOSH ingestion with malformed vector | Semantic failure, gracefully ignores - PASS |
| **Unsafe LLM Output (Hallucination)**| High | Medium | `MURPHY` independent risk validation | If `MURPHY` hallucinates, it could bypass | Redundant LLM calls / Fail-Closed schema | Malformed JSON schema response | Rejects and sets `UNKNOWN` risk - PASS |
| **SQL Injection** | Low | Critical | ORM (SQLAlchemy) parameterized queries | None | None | Standard SQLi probing on `/tasks/` | Safely escaped by ORM - PASS |
