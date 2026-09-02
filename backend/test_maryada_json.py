import json
from agents.nodes.maryada import maryada_node

def run():
    print("Testing MARYADA JSON output with local Ollama...")
    state = {
        "intent": "What is the policy regarding timesheets?",
        "plan": {"summary": "Fetch policy", "steps": ["Read doc"]},
        "risk_report": {"risk_level": "LOW", "failure_modes": [], "security_concerns": [], "recommendation": "PROCEED"},
        "errors": []
    }
    result = maryada_node(state)
    print("RESULT:", json.dumps(result, indent=2))

if __name__ == "__main__":
    run()
