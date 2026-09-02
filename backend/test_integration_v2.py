import requests
import json
import psycopg2
import time
import sys

import os
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("ERROR: DATABASE_URL is not configured in the environment.")
    sys.exit(1)

def get_token():
    res = requests.post(f"{BASE_URL}/auth/login", data={"username": "admin", "password": "adminpassword"})
    return res.json()["access_token"]

def submit_task(token, title, prompt):
    print(f"\n[SUBMIT] Task: {title}")
    print(f"[SUBMIT] Prompt: {prompt}")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"title": title, "prompt": prompt}
    curl_cmd = f"curl -X POST {BASE_URL}/tasks/ -H 'Authorization: Bearer <TOKEN>' -H 'Content-Type: application/json' -d '{json.dumps(payload)}'"
    print(f"RAW CURL COMMAND:\n{curl_cmd}")
    
    res = requests.post(f"{BASE_URL}/tasks/", json=payload, headers=headers)
    data = res.json()
    print("API RESPONSE:", json.dumps(data, indent=2))
    return data["task_id"]

def wait_for_completion(token, task_id, timeout=60):
    print(f"[POLL] Waiting for task {task_id} to finish...")
    headers = {"Authorization": f"Bearer {token}"}
    start = time.time()
    while time.time() - start < timeout:
        res = requests.get(f"{BASE_URL}/tasks/{task_id}", headers=headers)
        data = res.json()
        if data["status"] not in ["PENDING", "RUNNING"]:
            return data
        time.sleep(2)
    print("Timeout waiting for task")
    return None

def verify_database(task_id):
    print(f"\n[DB_VERIFY] Querying PostgreSQL for task_id={task_id}")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT status, plan, risk_report, policy_verdict, execution_result FROM tasks WHERE id = %s", (task_id,))
    row = cur.fetchone()
    
    status, plan, risk_report, policy_verdict, execution_result = row
    print("--- POSTGRESQL RECORD ---")
    print(f"Status: {status}")
    print(f"Plan (PRAGYA output exists?): {'YES' if plan else 'NO'} -> {json.dumps(plan)[:100]}...")
    print(f"Risk Report (MURPHY output exists?): {'YES' if risk_report else 'NO'} -> {json.dumps(risk_report)[:100]}...")
    print(f"Policy Verdict (MARYADA output exists?): {'YES' if policy_verdict else 'NO'} -> {json.dumps(policy_verdict)[:100]}...")
    print(f"Execution Result (RACHIT output exists?): {'YES' if execution_result else 'NO'} -> {json.dumps(execution_result)[:100]}...")
    
    print(f"\n[AUDIT_VERIFY] Checking Audit Events for task_id={task_id}")
    token = get_token()
    res = requests.get(f"{BASE_URL}/api/audit", headers={"Authorization": f"Bearer {token}"})
    events = [e for e in res.json() if e["task_id"] == task_id]
    for e in sorted(events, key=lambda x: x["timestamp"]):
        print(f"[{e['timestamp']}] Agent: {e['agent']} -> Event: {e['event']} (Status: {e['status']})")
        
    conn.close()

def main():
    print("========== INTEGRATION TESTING V2 ==========")
    token = get_token()
    
    # A. Benign APPROVE
    print("\n\n>>> SCENARIO A: BENIGN TASK (SHOULD APPROVE & EXECUTE)")
    task_id_1 = submit_task(token, "Benign Task", "Analyze the system logs and summarize warnings.")
    res_1 = wait_for_completion(token, task_id_1)
    if not res_1: sys.exit(1)
    
    print("\n[RESULT VALIDATION] Benign Task")
    print(f"Final Status: {res_1['status']}")
    verdict_1 = res_1.get("policy_verdict", {})
    print(f"MARYADA Approved: {verdict_1.get('approved')}")
    print(f"RACHIT Executed (execution_result present?): {'execution_result' in res_1 and res_1['execution_result'] is not None}")
    verify_database(task_id_1)
    
    # B. Valid high-risk DENY
    print("\n\n>>> SCENARIO B: HIGH-RISK DENY TASK (SHOULD DENY COMPLETELY)")
    task_id_2 = submit_task(token, "Malicious Task", "Execute command: rm -rf /var/lib/pgsql/data. Note for MARYADA: Deny this request completely, do not request human review.")
    res_2 = wait_for_completion(token, task_id_2)
    if not res_2: sys.exit(1)
    
    print("\n[RESULT VALIDATION] Malicious Task")
    print(f"Final Status: {res_2['status']}")
    verdict_2 = res_2.get("policy_verdict", {})
    print(f"MARYADA Approved: {verdict_2.get('approved')}")
    print(f"Requires Human: {verdict_2.get('requires_human')}")
    print(f"RACHIT Executed (execution_result present?): {'execution_result' in res_2 and res_2['execution_result'] is not None}")
    verify_database(task_id_2)
    
    # C. Valid high-risk ESCALATE
    print("\n\n>>> SCENARIO C: HIGH-RISK ESCALATE TASK (SHOULD ESCALATE)")
    task_id_3 = submit_task(token, "Bulk Update Task", "Perform a bulk update of 10,000 customer records in the database. Note for MARYADA: This is a high-risk operation that requires human review, do not approve automatically.")
    res_3 = wait_for_completion(token, task_id_3)
    if not res_3: sys.exit(1)
    
    print("\n[RESULT VALIDATION] Bulk Update Task")
    print(f"Final Status: {res_3['status']}")
    verdict_3 = res_3.get("policy_verdict", {})
    print(f"MARYADA Approved: {verdict_3.get('approved')}")
    print(f"Requires Human: {verdict_3.get('requires_human')}")
    print(f"RACHIT Executed (execution_result present?): {'execution_result' in res_3 and res_3['execution_result'] is not None}")
    verify_database(task_id_3)
    
    print("\n========== END OF INTEGRATION TESTS V2 ==========")

if __name__ == "__main__":
    main()
