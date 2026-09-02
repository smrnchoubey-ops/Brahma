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

print("--- 1. LOGGING IN ---")
login_data = {"username": "admin", "password": "adminpassword"}
res = requests.post(f"{BASE_URL}/auth/login", data=login_data)
token = res.json()["access_token"]

print("\n--- 2. SUBMITTING TASK VIA API ---")
task_payload = {"title": "Agent Integration Test", "prompt": "Analyze the log files for errors."}
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
res = requests.post(f"{BASE_URL}/tasks/", json=task_payload, headers=headers)
task_id = res.json().get("task_id")

print(f"\n--- 3. FETCHING TASK STATUS VIA API (Checking for real LangGraph execution) ---")
res = requests.get(f"{BASE_URL}/tasks/{task_id}", headers=headers)
task_data = res.json()
print("TASK PLAN DATA:", json.dumps(task_data.get("plan"), indent=2))
print("EXPECTED: Dynamic plan based on intent 'Analyze the log files for errors.'")
print("ACTUAL: Hardcoded 'Transfer funds to vendor'")

print("\n--- 4. CHECKING POSTGRESQL DB FOR LANGGRAPH STATE ---")
conn = psycopg2.connect(DB_URL)
cur = conn.cursor()
cur.execute("SELECT plan FROM tasks WHERE id = %s;", (task_id,))
row = cur.fetchone()
print("DB PLAN:", row[0])
conn.close()
