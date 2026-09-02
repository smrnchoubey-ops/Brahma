import os
from litellm import completion

def get_llm_config():
    """
    Returns the centralized LLM configuration for the BRAHMA COS project.
    """
    # Environment variables determine the active model
    provider = os.getenv("LLM_PROVIDER", "openrouter")
    model_name = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")
    
    # If the model name doesn't already include the provider prefix, add it.
    if provider and not model_name.startswith(provider + "/"):
        full_model = f"{provider}/{model_name}"
    else:
        full_model = model_name
        
    api_key = os.getenv("OPENROUTER_API_KEY") if provider == "openrouter" else os.getenv("LLM_API_KEY")
        
    return {
        "model": full_model,
        "api_key": api_key,
        "base_url": os.getenv("LLM_BASE_URL", None),
        "provider": provider
    }

def print_llm_config():
    config = get_llm_config()
    print("="*50)
    print("BRAHMA COS - CENTRALIZED LLM CONFIGURATION")
    print(f"Provider      : {config['provider']}")
    print(f"Model         : {config['model']}")
    print(f"API Key Found : {'YES' if config['api_key'] else 'NO'}")
    print(f"Base URL      : {config['base_url']}")
    print("="*50)

import time

def call_llm(messages, temperature=0.0):
    """
    Centralized function to invoke the LLM. 
    Handles routing through litellm securely, with exponential backoff retry.
    """
    config = get_llm_config()
    
    max_retries = 3
    base_delay = 2
    
    for attempt in range(max_retries):
        try:
            response = completion(
                model=config["model"],
                messages=messages,
                api_key=config["api_key"],
                base_url=config["base_url"],
                temperature=temperature,
                max_tokens=2048,
                timeout=30.0
            )
            return response
        except Exception as e:
            print(f"[LLM Core Error] Attempt {attempt + 1}/{max_retries} failed for model {config['model']}: {str(e)}")
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                print(f"[LLM Retry] Waiting {delay} seconds before next attempt...")
                time.sleep(delay)
            else:
                print(f"[LLM Core Error] Max retries exhausted.")
                raise e
