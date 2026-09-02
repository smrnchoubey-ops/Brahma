import os
from dotenv import load_dotenv
import logging

# Ensure override=True so the environment variables from .env take precedence
load_dotenv(override=True)

from app.core.llm import print_llm_config, call_llm

logging.basicConfig(level=logging.INFO)

def test_llm():
    print_llm_config()
    
    # Check if OPENROUTER_API_KEY exists
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("RESULT: FAILED - OPENROUTER_API_KEY is completely missing from environment.")
        return False
        
    print(f"DEBUG: Found OPENROUTER_API_KEY of length {len(api_key)}")
        
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Reply with only the word 'PONG'."},
        {"role": "user", "content": "PING"}
    ]
    
    try:
        response = call_llm(messages)
        content = response.choices[0].message.content
        print(f"LLM Response: {content}")
        print("RESULT: SUCCESS")
        return True
    except Exception as e:
        print(f"RESULT: FAILED - {str(e)}")
        return False

if __name__ == "__main__":
    test_llm()
