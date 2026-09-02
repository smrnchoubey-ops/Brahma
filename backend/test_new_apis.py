import requests

BASE_URL = "http://127.0.0.1:8000"

def test_apis():
    print("Testing Backend APIs...")
    
    # Login to get token
    login_data = {"username": "admin", "password": "adminpassword"}
    response = requests.post(f"{BASE_URL}/auth/login", data=login_data)
    
    if response.status_code != 200:
        print(f"Login Failed: {response.text}")
        return
        
    token = response.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    
    print("\n1. Testing /api/metrics")
    res = requests.get(f"{BASE_URL}/api/metrics", headers=headers)
    print(f"Status: {res.status_code}")
    print(res.json())
    
    print("\n2. Testing /api/agents")
    res = requests.get(f"{BASE_URL}/api/agents", headers=headers)
    print(f"Status: {res.status_code}")
    print(res.json())
    
    print("\n3. Testing /api/audit")
    res = requests.get(f"{BASE_URL}/api/audit", headers=headers)
    print(f"Status: {res.status_code}")
    print(res.json())

if __name__ == "__main__":
    test_apis()
