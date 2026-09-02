import requests
import os
from dotenv import load_dotenv

load_dotenv(override=True)
api_key = os.getenv("OPENROUTER_API_KEY")

if not api_key:
    print("NO API KEY")
    exit(1)

print("Testing raw request to openrouter...")
try:
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "http://localhost",
            "X-Title": "Brahma COS Test"
        },
        json={
            "model": "liquid/lfm-2.5-2.6b:free",
            "messages": [
                {"role": "user", "content": "PING"}
            ]
        },
        timeout=10
    )
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Exception: {e}")
