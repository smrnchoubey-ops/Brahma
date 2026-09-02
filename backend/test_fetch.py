import requests
import json

BASE_URL = "http://127.0.0.1:8000"

print("--- LOGGING IN (AFTER RESTART) ---")
login_data = {"username": "admin", "password": "adminpassword"}
res = requests.post(f"{BASE_URL}/auth/login", data=login_data)
token = res.json()["access_token"]

with open("temp_task_id.txt", "r") as f:
    task_id = f.read().strip()

print(f"\n--- FETCHING TASK {task_id} VIA API ---")
headers = {"Authorization": f"Bearer {token}"}
print(f"REQUEST:\ncurl -X GET {BASE_URL}/tasks/{task_id} -H 'Authorization: Bearer <TOKEN>'")
res = requests.get(f"{BASE_URL}/tasks/{task_id}", headers=headers)
print("RESPONSE:", json.dumps(res.json(), indent=2))
