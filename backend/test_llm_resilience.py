import json
from agents.nodes.pragya import pragya_node
from agents.nodes.murphy import murphy_node
from agents.nodes.maryada import maryada_node
from agents.nodes.kosh import kosh_node
from app.core.llm import call_llm
import unittest.mock as mock

class ResilienceTests:
    def test_pragya_empty_response(self):
        print("\n--- TEST: PRAGYA EMPTY RESPONSE ---")
        with mock.patch('agents.nodes.pragya.call_llm') as mock_llm:
            mock_response = mock.Mock()
            mock_response.choices = [mock.Mock(message=mock.Mock(content=""))]
            mock_llm.return_value = mock_response
            
            state = {"intent": "do something"}
            result = pragya_node(state)
            print("RESULT:", json.dumps(result, indent=2))
            
    def test_pragya_malformed_json(self):
        print("\n--- TEST: PRAGYA MALFORMED JSON ---")
        with mock.patch('agents.nodes.pragya.call_llm') as mock_llm:
            mock_response = mock.Mock()
            mock_response.choices = [mock.Mock(message=mock.Mock(content="{'summary': 'bad json'}"))]
            mock_llm.return_value = mock_response
            
            state = {"intent": "do something"}
            result = pragya_node(state)
            print("RESULT:", json.dumps(result, indent=2))

    def test_pragya_timeout(self):
        print("\n--- TEST: PRAGYA TIMEOUT (LiteLLM Exception) ---")
        with mock.patch('agents.nodes.pragya.call_llm') as mock_llm:
            mock_llm.side_effect = Exception("litellm.TimeoutError: Request timed out")
            
            state = {"intent": "do something"}
            result = pragya_node(state)
            print("RESULT:", json.dumps(result, indent=2))

    def test_murphy_missing_plan(self):
        print("\n--- TEST: MURPHY MISSING PLAN ---")
        state = {"plan": None, "errors": ["PRAGYA FAILED"]}
        result = murphy_node(state)
        print("RESULT:", json.dumps(result, indent=2))
        
    def test_murphy_malformed_json(self):
        print("\n--- TEST: MURPHY MALFORMED JSON ---")
        with mock.patch('agents.nodes.murphy.call_llm') as mock_llm:
            mock_response = mock.Mock()
            mock_response.choices = [mock.Mock(message=mock.Mock(content="I think this is high risk."))]
            mock_llm.return_value = mock_response
            
            state = {"plan": {"summary": "test"}}
            result = murphy_node(state)
            print("RESULT:", json.dumps(result, indent=2))

    def test_maryada_missing_risk(self):
        print("\n--- TEST: MARYADA MISSING RISK REPORT ---")
        state = {"risk_report": None, "errors": ["MURPHY FAILED"]}
        result = maryada_node(state)
        print("RESULT:", json.dumps(result, indent=2))

    def test_maryada_unknown_risk(self):
        print("\n--- TEST: MARYADA UNKNOWN RISK OVERRIDE ---")
        with mock.patch('agents.nodes.maryada.call_llm') as mock_llm:
            mock_response = mock.Mock()
            mock_response.choices = [mock.Mock(message=mock.Mock(content='{"risk_tier": "UNKNOWN", "approved": true, "requires_human": false, "justification": "Looks fine to me"}'))]
            mock_llm.return_value = mock_response
            
            state = {"risk_report": {"risk_level": "UNKNOWN", "failure_modes": [], "security_concerns": [], "recommendation": ""}}
            result = maryada_node(state)
            print("RESULT:", json.dumps(result, indent=2))

    def test_maryada_high_risk_override(self):
        print("\n--- TEST: MARYADA HIGH RISK OVERRIDE ---")
        with mock.patch('agents.nodes.maryada.call_llm') as mock_llm:
            mock_response = mock.Mock()
            # LLM hallucinates approval for high risk
            mock_response.choices = [mock.Mock(message=mock.Mock(content='{"risk_tier": "HIGH", "approved": true, "requires_human": false, "justification": "I approve this high risk task"}'))]
            mock_llm.return_value = mock_response
            
            state = {"risk_report": {"risk_level": "HIGH", "failure_modes": [], "security_concerns": [], "recommendation": ""}}
            result = maryada_node(state)
            print("RESULT:", json.dumps(result, indent=2))

    def test_maryada_medium_risk(self):
        print("\n--- TEST: MARYADA MEDIUM RISK -> HUMAN REVIEW ---")
        with mock.patch('agents.nodes.maryada.call_llm') as mock_llm:
            mock_response = mock.Mock()
            mock_response.choices = [mock.Mock(message=mock.Mock(content='{"risk_tier": "MEDIUM", "approved": false, "requires_human": true, "justification": "Requires review"}'))]
            mock_llm.return_value = mock_response
            
            state = {"risk_report": {"risk_level": "MEDIUM", "failure_modes": [], "security_concerns": [], "recommendation": ""}}
            result = maryada_node(state)
            print("RESULT:", json.dumps(result, indent=2))
            assert result["policy_verdict"]["requires_human"] == True
            assert result["policy_verdict"]["approved"] == False

    def test_kosh_database_failure(self):
        print("\n--- TEST: KOSH DATABASE FAILURE ---")
        with mock.patch('agents.nodes.kosh.kosh.retrieve') as mock_retrieve:
            mock_retrieve.side_effect = Exception("PostgreSQL connection refused")
            
            state = {"intent": "do something"}
            result = kosh_node(state)
            print("RESULT:", json.dumps(result, indent=2))
            assert result["status"] == "KOSH_FAILED"
            assert "KOSH Error: PostgreSQL connection refused" in result["errors"]

    def test_llm_retry_behavior(self):
        print("\n--- TEST: LLM RETRY BEHAVIOR ---")
        with mock.patch('app.core.llm.completion') as mock_completion:
            mock_completion.side_effect = Exception("Transient LLM Error")
            try:
                call_llm([{"role": "user", "content": "Hello"}])
            except Exception as e:
                print(f"Caught expected exception after retries: {e}")
            assert mock_completion.call_count == 3
            print(f"Total Retries Attempted: {mock_completion.call_count}")

    def test_llm_retry_success(self):
        print("\n--- TEST: LLM RETRY THEN SUCCEED ---")
        with mock.patch('app.core.llm.completion') as mock_completion:
            mock_response = mock.Mock()
            mock_response.choices = [mock.Mock(message=mock.Mock(content="Success!"))]
            mock_completion.side_effect = [Exception("Transient LLM Error"), mock_response]
            
            result = call_llm([{"role": "user", "content": "Hello"}])
            assert mock_completion.call_count == 2
            assert result.choices[0].message.content == "Success!"
            print(f"Total Retries Attempted: {mock_completion.call_count}. Final result: {result.choices[0].message.content}")

    def test_llm_rate_limit(self):
        print("\n--- TEST: LLM RATE LIMIT (HTTP 429) ---")
        with mock.patch('app.core.llm.completion') as mock_completion:
            from litellm.exceptions import RateLimitError
            import httpx
            mock_completion.side_effect = RateLimitError(message="Rate Limit Exceeded", response=httpx.Response(status_code=429, request=httpx.Request("GET", "https://api.openai.com/v1/completions")), llm_provider="openai", model="gpt-4")
            
            try:
                call_llm([{"role": "user", "content": "Hello"}])
            except Exception as e:
                print(f"Caught expected exception after retries: {e}")
            assert mock_completion.call_count == 3
            print(f"Total Retries Attempted on Rate Limit: {mock_completion.call_count}")

    def test_agent_crash(self):
        print("\n--- TEST: AGENT CRASH MID-WORKFLOW ---")
        from main import run_agent_workflow
        import app.models.task as task_model
        with mock.patch('main.SessionLocal') as mock_session_maker, \
             mock.patch('agents.nodes.murphy.murphy_node') as mock_murphy, \
             mock.patch('main.log_audit_event') as mock_audit, \
             mock.patch('agents.nodes.karma.log_audit_event'), \
             mock.patch('agents.nodes.kosh.log_audit_event'), \
             mock.patch('agents.nodes.pragya.log_audit_event'):
            
            mock_session = mock.Mock()
            mock_session_maker.return_value = mock_session
            
            mock_task = mock.Mock()
            mock_task.id = 999
            mock_task.status = "PENDING"
            mock_session.query.return_value.filter.return_value.first.return_value = mock_task
            
            mock_murphy.side_effect = ZeroDivisionError("Simulated division by zero crash")
            
            try:
                run_agent_workflow(999, "do something")
            except Exception:
                pass
            
            assert mock_task.status == "FAILED"
            assert "Workflow failed due to internal exception" in mock_task.execution_result["message"]
            mock_audit.assert_called_with(999, "SYSTEM", "Workflow Crash", "FAILED", {"error": "Simulated division by zero crash"})
            print(f"Agent crash correctly trapped. Task status: {mock_task.status}")

if __name__ == "__main__":
    tests = ResilienceTests()
    tests.test_pragya_empty_response()
    tests.test_pragya_malformed_json()
    tests.test_pragya_timeout()
    tests.test_murphy_missing_plan()
    tests.test_murphy_malformed_json()
    tests.test_maryada_missing_risk()
    tests.test_maryada_unknown_risk()
    tests.test_maryada_high_risk_override()
    tests.test_maryada_medium_risk()
    tests.test_kosh_database_failure()
    tests.test_llm_retry_behavior()
    tests.test_llm_retry_success()
    tests.test_llm_rate_limit()
    tests.test_agent_crash()
