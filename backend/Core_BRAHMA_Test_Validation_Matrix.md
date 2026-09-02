# Core BRAHMA Test Validation Matrix

| Test Case | Input | Expected Result | Actual Result | PASS/FAIL | Evidence | Root Cause | Corrective Action |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **API Task Creation** | Valid POST to `/tasks/` | 200 OK, returns task ID, stores in DB | 200 OK, returns task ID, stores in DB | PASS | `test_integration.py` logs | N/A | N/A |
| **LLM Resilience (Timeout/Rate Limit)** | Mocked OpenRouter Timeout | System fails closed, PRAGYA -> FAILED, MARYADA -> BLOCKED | System fails closed, MARYADA -> BLOCKED | PASS | `test_llm_resilience.py` | LiteLLM Exceptions handled by agent nodes | N/A |
| **Malformed Output Resilience** | `llama3.2:3b` truncates JSON schema | JSON parse failure caught, Risk=UNKNOWN, MARYADA=BLOCKED | JSON parse failure caught, Risk=UNKNOWN, MARYADA=BLOCKED | PASS | Uvicorn stdout logs | Small LLM truncated token limit (128 default) | Enforced `max_tokens=2048` and tighter prompt |
| **End-to-End Success Path** | Low risk "timesheets" request | KARMA->KOSH->PRAGYA->MURPHY->MARYADA(Approve)->RACHIT | Executed successfully, DB Status = COMPLETED | PASS | `test_kosh_integration.py` execution output | Stable JSON configuration achieved | N/A |
| **High-Risk Governance Gate** | High risk "Delete DB" request | MARYADA explicitly blocks, RACHIT does not execute | MARYADA explicitly blocked, RACHIT did not execute | PASS | `test_governance.py` | MARYADA explicit evaluation condition `risk_tier == 'HIGH'` | N/A |
| **Unauthorized API Access** | Missing Bearer JWT token | 401 Unauthorized across protected endpoints | 401 Unauthorized | PASS | Terminal curl test logs | FastAPI `Depends(get_current_user)` | N/A |
| **Knowledge Retrieval Context Injection** | Upload document, submit task | KOSH semantic search finds doc, PRAGYA uses it | KOSH semantic search finds doc, PRAGYA uses it | PASS | `test_kosh_integration.py` plan generated via context | `semantic_search()` pgvector similarity matches | N/A |
