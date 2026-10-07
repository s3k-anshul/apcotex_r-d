"""
dev-scripts/test_live_recipe_fix.py

Tests live recipe generation against the running backend server:
1. Login to retrieve bearer token.
2. Test Case 1: Exact failure case - "20% Acrylonitrile NBR" with report 554f0130-8a1d-4873-ba7f-5c1128af9270 and empty properties.
3. Test Case 2: Target properties case - "20% Acrylonitrile NBR" with report 554f0130-8a1d-4873-ba7f-5c1128af9270 and target constraints.
4. Test Case 3: Different compound case - "Low styrene SBR" with report a62f2682-badc-445b-b09b-27e53a6b5b1e.
"""
import requests
import json
import time
import sys

BASE_URL = "http://127.0.0.1:8000/api/v1"

def login():
    print("--> Logging in as admin...")
    res = requests.post(f"{BASE_URL}/auth/login", json={"username": "admin", "password": "admin123"})
    if res.status_code != 200:
        print(f"Login failed: {res.status_code} - {res.text}")
        sys.exit(1)
    data = res.json()["data"]
    token = data["access_token"]
    print("    Logged in successfully!")
    return token

def test_generate(token, test_name, payload):
    print(f"\n==================================================")
    print(f"RUNNING: {test_name}")
    print(f"==================================================")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # Step 1: Create cycle
    print(f"--> POST /recipe/cycles with payload: {json.dumps(payload)}")
    res = requests.post(f"{BASE_URL}/recipe/cycles", json=payload, headers=headers)
    if res.status_code != 200:
        print(f"FAILED to create cycle: {res.status_code} - {res.text}")
        return False
    cycle = res.json()["data"]
    cycle_id = cycle["id"]
    print(f"    Cycle created successfully: ID = {cycle_id}")
    
    # Step 2: Generate recipes
    t0 = time.time()
    print(f"--> POST /recipe/cycles/{cycle_id}/generate...")
    res = requests.post(f"{BASE_URL}/recipe/cycles/{cycle_id}/generate", headers=headers, timeout=180)
    dur = time.time() - t0
    print(f"    Generation completed in {dur:.2f}s with status {res.status_code}")
    
    if res.status_code != 200:
        print(f"FAILED generation: {res.status_code} - {res.text}")
        return False
        
    candidates = res.json()["data"]
    print(f"--> Received {len(candidates)} candidates.")
    
    # Assertions
    assert len(candidates) == 5, f"Expected exactly 5 candidates, got {len(candidates)}"
    
    for i, c in enumerate(candidates):
        c_name = c.get("name")
        c_data = c.get("recipe_data", {})
        c_stages = c_data.get("stages", [])
        c_confidence = c.get("confidence_score")
        c_refs = c.get("patent_references", [])
        
        print(f"  Candidate #{i+1}: {c_name} (Confidence: {c_confidence}%)")
        print(f"    Stages count: {len(c_stages)}")
        stage_names = [s.get("stage_name") for s in c_stages]
        print(f"    Stage names: {stage_names}")
        print(f"    Patent refs: {c_refs}")
        
        # Check stages and parameters
        assert len(c_stages) > 0, f"Candidate {i+1} has no stages"
        for st in c_stages:
            st_name = st.get("stage_name")
            params = st.get("parameters", [])
            print(f"      [{st_name}] has {len(params)} parameters")
            
    print(f"--> SUCCESS for {test_name}!\n")
    return True

if __name__ == "__main__":
    token = login()
    
    # Test 1: Exact failure case - 20% Acrylonitrile NBR with report 554f0130-8a1d-4873-ba7f-5c1128af9270, empty properties
    p1 = {
        "target_product": "20% Acrylonitrile NBR",
        "patent_report_id": "554f0130-8a1d-4873-ba7f-5c1128af9270",
        "target_properties": [],
        "competitor_data": []
    }
    s1 = test_generate(token, "Test 1: Exact Failure Case (20% Acrylonitrile NBR, Empty Properties)", p1)
    
    # Test 2: Target properties case - 20% Acrylonitrile NBR with target properties
    p2 = {
        "target_product": "20% Acrylonitrile NBR",
        "patent_report_id": "554f0130-8a1d-4873-ba7f-5c1128af9270",
        "target_properties": [
            {"id": "prop_1", "feature": "Bound ACN Content", "unit": "%", "min": "19.0", "max": "21.0"},
            {"id": "prop_2", "feature": "Mooney Viscosity ML(1+4) 100C", "unit": "MU", "min": "45.0", "max": "55.0"},
            {"id": "prop_3", "feature": "Tensile Strength", "unit": "MPa", "min": "22.0", "max": None}
        ],
        "competitor_data": []
    }
    s2 = test_generate(token, "Test 2: Target Properties Case (20% Acrylonitrile NBR with constraints)", p2)
    
    # Test 3: Different compound case - Low styrene SBR
    p3 = {
        "target_product": "Low styrene SBR",
        "patent_report_id": "a62f2682-badc-445b-b09b-27e53a6b5b1e",
        "target_properties": [
            {"id": "prop_sbr_1", "feature": "Bound Styrene Content", "unit": "%", "min": "15.0", "max": "18.0"}
        ],
        "competitor_data": []
    }
    s3 = test_generate(token, "Test 3: Different Compound (Low styrene SBR)", p3)
    
    print("\n================== SUMMARY ==================")
    print(f"Test 1 (NBR Empty Properties): {'PASSED' if s1 else 'FAILED'}")
    print(f"Test 2 (NBR With Target Properties): {'PASSED' if s2 else 'FAILED'}")
    print(f"Test 3 (Low styrene SBR): {'PASSED' if s3 else 'FAILED'}")
    if s1 and s2 and s3:
        print("ALL LIVE TESTS PASSED SUCCESSFULLY!")
    else:
        print("SOME TESTS FAILED!")
        sys.exit(1)
