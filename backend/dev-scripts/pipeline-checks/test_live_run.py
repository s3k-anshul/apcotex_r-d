import requests
import time

BASE_URL = "http://127.0.0.1:8000/api/v1"

def main():
    print("[Test F] Live NBR run...")
    
    # Login
    res = requests.post(f"{BASE_URL}/auth/login", json={"username": "admin", "password": "Admin@123!"})
    token = res.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    payload = {
        "compound_name": "Low Acrylonitrile NBR",
        "competitors": [],
        "mentioned_websites": [],
        "selected_sources": ["Google Patents", "Espacenet", "USPTO"],
        "jurisdictions": ["US", "EP", "IN"]
    }
    
    resp = requests.post(f"{BASE_URL}/research-runs", json=payload, headers=headers)
    print(f"Start response: {resp.status_code}")
    if resp.status_code != 201:
        print(resp.json())
        return
        
    run_id = resp.json()["data"]["id"]
    
    while True:
        poll_resp = requests.get(f"{BASE_URL}/research-runs/{run_id}", headers=headers)
        data = poll_resp.json()["data"]
        status = data["status"]
        
        # We also added stage, progress, error to the schema via heartbeat!
        stage = data.get("stage")
        progress = data.get("progress")
        error = data.get("error")
        
        print(f"Polling {run_id}... Status: {status} | Stage: {stage} | Progress: {progress}")
        if error:
            print(f"Error: {error}")
            
        if status in ["COMPLETED", "COMPLETED_PARTIAL", "FAILED", "CANCELLED", "LLM_PROVIDER_EXHAUSTED"]:
            print(f"Reached terminal status: {status}")
            break
            
        time.sleep(3)

if __name__ == "__main__":
    main()
