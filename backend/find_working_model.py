import requests
import os
from dotenv import load_dotenv

load_dotenv(override=True)
api_key = os.getenv("OPENROUTER_API_KEY")

models = [
    "thinkingmachines/inkling:free",
    "thinkingmachines/inkling-small:free",
    "dots-studio/dots-3-note-preview:free",
    "inclusionai/ling-3.0-flash-fin:free",
    "nvidia/nemotron-3.5-lightning:free",
    "z-ai/glm-5.2:free"
]

working_model = None
for model in models:
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "http://localhost",
                "X-Title": "Brahma COS Test"
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "PING"}]
            },
            timeout=10
        )
        if response.status_code == 200:
            print(f"SUCCESS: {model}")
            working_model = model
            break
        else:
            print(f"FAILED: {model} with status {response.status_code}")
    except Exception as e:
        print(f"FAILED: {model} with exception {e}")

if working_model:
    # Update .env
    with open(".env", "r") as f:
        lines = f.readlines()
    with open(".env", "w") as f:
        for line in lines:
            if line.startswith("LLM_MODEL="):
                f.write(f"LLM_MODEL={working_model}\n")
            else:
                f.write(line)
    print("UPDATED .env")
