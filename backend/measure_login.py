import requests
import time

url = "http://localhost:8000/auth/login"
data = {
    "username": "admin",
    "password": "adminpassword"
}

start_time = time.time()
response = requests.post(url, data=data)
end_time = time.time()

print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}")
print(f"Login Time: {(end_time - start_time) * 1000:.2f} ms")
