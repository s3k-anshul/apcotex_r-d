import requests
import json
import time

BASE_URL = "http://localhost:8000/api/v1"

def run_test(compound_name):
    # Login
    res = requests.post(f"{BASE_URL}/auth/login", json={"username": "admin", "password": "Admin@123!"})
    token = res.json()["data"]["access_token"]
    
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start run
    payload = {
        "compound_name": compound_name,
        "competitors": [],
        "jurisdictions": ["US"]
    }
    res = requests.post(f"{BASE_URL}/research-runs", json=payload, headers=headers)
    print(f"[{compound_name}] Start response:", res.status_code)
    run_id = res.json()["data"]["id"]
    
    # Poll
    for _ in range(10):
        res = requests.get(f"{BASE_URL}/research-runs/{run_id}", headers=headers)
        status = res.json()["data"]["status"]
        print(f"[{compound_name}] Polling {run_id}... Status: {status}")
        if status in ["COMPLETED", "FAILED", "LLM_PROVIDER_EXHAUSTED"]:
            print(f"[{compound_name}] Reached terminal status: {status}")
            break
        time.sleep(2)
        
if __name__ == "__main__":
    run_test("Test B")
    print("-" * 40)
    run_test("Test C")
    print("-" * 40)
    run_test("Test D")
