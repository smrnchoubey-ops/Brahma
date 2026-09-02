import requests
import json
import psycopg2
import os
import sys
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("ERROR: DATABASE_URL is not configured in the environment.")
    sys.exit(1)

# 1. Login
print("--- LOGGING IN ---")
login_data = {"username": "admin", "password": "adminpassword"}
res = requests.post(f"{BASE_URL}/auth/login", data=login_data)
token = res.json()["access_token"]
print(f"Token obtained: {token[:10]}...")

# 2. Create Task via API
print("\n--- CREATING TASK VIA API ---")
task_payload = {"title": "Docker Postgres Test", "prompt": "Verify docker postgres persistence via API"}
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
print(f"REQUEST:\ncurl -X POST {BASE_URL}/tasks/ -H 'Authorization: Bearer <TOKEN>' -H 'Content-Type: application/json' -d '{json.dumps(task_payload)}'")
res = requests.post(f"{BASE_URL}/tasks/", json=task_payload, headers=headers)
task_data = res.json()
print("RESPONSE:", json.dumps(task_data, indent=2))
task_id = task_data.get("task_id")

# 3. Query PostgreSQL directly
print("\n--- QUERYING POSTGRES DIRECTLY ---")
query = "SELECT id, title, prompt, status FROM tasks WHERE id = %s;"
print(f"QUERY: {query}  (with id={task_id})")
conn = psycopg2.connect(DB_URL)
cur = conn.cursor()
cur.execute(query, (task_id,))
row = cur.fetchone()
print("RESULT ROW:", row)
conn.close()

# 4. Save Task ID for later
with open("temp_task_id.txt", "w") as f:
    f.write(str(task_id))
