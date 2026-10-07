"""
dev-scripts/test_live_customer_trial.py

Comprehensive test suite verifying Customer Trial creation and response serialization:
1. Login as admin.
2. Verification of the previously failed request (saved recipe 09a39691-7b25-4c3a-9212-03cdf12aad74).
   - Verifies 200 OK response (no 500 / MissingGreenlet).
   - Verifies deduplication: re-uses the existing pending trial without creating a duplicate.
3. Test empty feedback (feedback = "") and empty target properties.
4. Test target properties:
   - A: No target properties
   - B: One target property
   - C: Multiple target properties
5. Test Customer Trial creation from a NORMAL saved recipe.
6. Test Customer Trial creation from an OPTIMIZED saved recipe.
7. Test Multi-generation optimization lineage:
   - Original Recipe -> Trial 1 -> 3 Optimized candidates -> Select Candidate B -> Save Recipe B -> Trial 2 with Recipe B -> verify parent_recipe_id and lineage.
"""
import requests
import json
import uuid
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

def test_live_customer_trials():
    token = login()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # Fetch saved recipes
    res = requests.get(f"{BASE_URL}/recipe/saved", headers=headers)
    assert res.status_code == 200, f"Failed to get saved recipes: {res.text}"
    saved_recipes = res.json()["data"]
    print(f"--> Retrieved {len(saved_recipes)} saved recipes.")
    
    normal_recipes = [r for r in saved_recipes if r.get("recipe_kind") == "NORMAL"]
    optimized_recipes = [r for r in saved_recipes if r.get("recipe_kind") == "OPTIMIZED"]
    print(f"    NORMAL saved recipes count: {len(normal_recipes)}")
    print(f"    OPTIMIZED saved recipes count: {len(optimized_recipes)}")
    
    assert len(normal_recipes) > 0, "Need at least one NORMAL saved recipe for tests"
    
    # -------------------------------------------------------------------------
    # TEST 1: The exact failure case (Saved Recipe 09a39691-7b25-4c3a-9212-03cdf12aad74)
    # -------------------------------------------------------------------------
    target_failed_id = "09a39691-7b25-4c3a-9212-03cdf12aad74"
    print(f"\n==================================================")
    print(f"TEST 1: Exact Failure Case & Retry Deduplication (Recipe {target_failed_id})")
    print(f"==================================================")
    
    # Check current pending count before
    p1 = {
        "saved_recipe_id": target_failed_id,
        "feedback_text": "Customer reported tackiness is slightly high. Please optimize surfactant dosage.",
        "actual_values": {"Mooney Viscosity": "52"},
        "target_values": {"Mooney Viscosity": "48"}
    }
    res = requests.post(f"{BASE_URL}/recipe/trials", json=p1, headers=headers)
    print(f"--> POST /recipe/trials status: {res.status_code}")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    trial1 = res.json()["data"]
    print(f"    Trial ID: {trial1['id']}")
    print(f"    Status: {trial1['status']}")
    print(f"    Feedback: {trial1['feedback_text']}")
    print(f"    Target values: {trial1['target_values']}")
    print(f"    Optimized candidates: {trial1['optimized_candidates']}")
    assert trial1["saved_recipe_id"] == target_failed_id
    assert trial1["status"] == "PENDING"
    assert trial1["optimized_candidates"] == []
    
    # Retry the exact request immediately — must return the SAME trial ID without creating a duplicate!
    res_retry = requests.post(f"{BASE_URL}/recipe/trials", json=p1, headers=headers)
    assert res_retry.status_code == 200
    trial1_retry = res_retry.json()["data"]
    assert trial1_retry["id"] == trial1["id"], f"Duplicate trial was created! Expected {trial1['id']}, got {trial1_retry['id']}"
    print("    Deduplication verified: exact same pending trial returned without duplicate creation!")
    print("--> TEST 1 PASSED!")

    # -------------------------------------------------------------------------
    # TEST 2: Empty customer feedback & empty target properties
    # -------------------------------------------------------------------------
    print(f"\n==================================================")
    print(f"TEST 2: Empty Customer Feedback & Empty Target Properties")
    print(f"==================================================")
    test_recipe_normal = normal_recipes[0]
    p2 = {
        "saved_recipe_id": test_recipe_normal["id"],
        "feedback_text": "",
        "actual_values": {},
        "target_values": {}
    }
    res = requests.post(f"{BASE_URL}/recipe/trials", json=p2, headers=headers)
    print(f"--> POST /recipe/trials with empty feedback status: {res.status_code}")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    trial2 = res.json()["data"]
    print(f"    Trial ID: {trial2['id']}")
    print(f"    Feedback text: '{trial2['feedback_text']}'")
    print(f"    Target values: {trial2['target_values']}")
    assert trial2["feedback_text"] == ""
    assert trial2["target_values"] == {}
    print("--> TEST 2 PASSED!")

    # -------------------------------------------------------------------------
    # TEST 3: Target properties variations
    # -------------------------------------------------------------------------
    print(f"\n==================================================")
    print(f"TEST 3: Target Properties Variations (None, One, Multiple)")
    print(f"==================================================")
    
    # 3A: No target properties
    p3a = {
        "saved_recipe_id": test_recipe_normal["id"],
        "feedback_text": "Variation test A - No target props",
        "target_values": {}
    }
    res_a = requests.post(f"{BASE_URL}/recipe/trials", json=p3a, headers=headers)
    assert res_a.status_code == 200
    print("    3A (No target properties): PASSED (200 OK)")

    # 3B: One target property
    p3b = {
        "saved_recipe_id": test_recipe_normal["id"],
        "feedback_text": "Variation test B - One target prop",
        "target_values": {"Mooney Viscosity": "50"}
    }
    res_b = requests.post(f"{BASE_URL}/recipe/trials", json=p3b, headers=headers)
    assert res_b.status_code == 200
    print("    3B (One target property): PASSED (200 OK)")

    # 3C: Multiple target properties
    p3c = {
        "saved_recipe_id": test_recipe_normal["id"],
        "feedback_text": "Variation test C - Multiple target props",
        "target_values": {"Mooney Viscosity": "50", "Tensile Strength": "24", "Bound ACN": "21"}
    }
    res_c = requests.post(f"{BASE_URL}/recipe/trials", json=p3c, headers=headers)
    assert res_c.status_code == 200
    t3c = res_c.json()["data"]
    assert len(t3c["target_values"]) == 3
    print("    3C (Multiple target properties): PASSED (200 OK)")
    print("--> TEST 3 PASSED!")

    # -------------------------------------------------------------------------
    # TEST 4: Original Saved Recipe (NORMAL)
    # -------------------------------------------------------------------------
    print(f"\n==================================================")
    print(f"TEST 4: Original Saved Recipe (NORMAL)")
    print(f"==================================================")
    p4 = {
        "saved_recipe_id": test_recipe_normal["id"],
        "feedback_text": "Feedback against original NORMAL saved recipe",
        "target_values": {"Gel Content": "< 5%"}
    }
    res_4 = requests.post(f"{BASE_URL}/recipe/trials", json=p4, headers=headers)
    assert res_4.status_code == 200
    t4 = res_4.json()["data"]
    assert t4["recipe_snapshot"]["recipe_kind"] == "NORMAL"
    print(f"    Trial ID: {t4['id']} created from NORMAL recipe {test_recipe_normal['recipe_name']}")
    print("--> TEST 4 PASSED!")

    # -------------------------------------------------------------------------
    # TEST 5: Optimized Saved Recipe (OPTIMIZED)
    # -------------------------------------------------------------------------
    print(f"\n==================================================")
    print(f"TEST 5: Previously Optimized Saved Recipe (OPTIMIZED)")
    print(f"==================================================")
    assert len(optimized_recipes) > 0, "Need at least one OPTIMIZED recipe for test 5"
    test_recipe_opt = optimized_recipes[0]
    p5 = {
        "saved_recipe_id": test_recipe_opt["id"],
        "feedback_text": "Feedback against previously OPTIMIZED saved recipe",
        "target_values": {"Tensile Strength": "> 25 MPa"}
    }
    res_5 = requests.post(f"{BASE_URL}/recipe/trials", json=p5, headers=headers)
    assert res_5.status_code == 200
    t5 = res_5.json()["data"]
    assert t5["recipe_snapshot"]["recipe_kind"] == "OPTIMIZED"
    print(f"    Trial ID: {t5['id']} created from OPTIMIZED recipe {test_recipe_opt['recipe_name']}")
    print(f"    Parent recipe in snapshot: {t5['recipe_snapshot'].get('parent_recipe_id')}")
    print("--> TEST 5 PASSED!")

    # -------------------------------------------------------------------------
    # TEST 6: Multi-Generation Optimization Lineage
    # -------------------------------------------------------------------------
    print(f"\n==================================================")
    print(f"TEST 6: Multi-Generation Optimization Lineage")
    print(f"==================================================")
    
    # Step A: Create trial on normal recipe
    p6_trial1 = {
        "saved_recipe_id": test_recipe_normal["id"],
        "feedback_text": "Multi-gen optimization lineage test",
        "target_values": {"Mooney Viscosity": "49"}
    }
    res_trial1 = requests.post(f"{BASE_URL}/recipe/trials", json=p6_trial1, headers=headers)
    assert res_trial1.status_code == 200
    t6_1 = res_trial1.json()["data"]
    trial1_id = t6_1["id"]
    print(f"    Step A: Created Customer Trial #1: ID = {trial1_id}")
    
    # Step B: Optimize trial #1
    print(f"    Step B: Running POST /recipe/trials/{trial1_id}/optimize...")
    res_opt = requests.post(f"{BASE_URL}/recipe/trials/{trial1_id}/optimize", headers=headers, timeout=120)
    assert res_opt.status_code == 200, f"Optimization failed: {res_opt.text}"
    candidates = res_opt.json()["data"]
    assert len(candidates) == 3, f"Expected exactly 3 candidates, got {len(candidates)}"
    print(f"    Received 3 optimized candidates: {[c['revision_label'] for c in candidates]}")
    
    # Step C: Select Candidate B (Revision B)
    cand_b = next((c for c in candidates if "B" in c["revision_label"]), candidates[1])
    res_sel = requests.post(f"{BASE_URL}/recipe/trials/{trial1_id}/select/{cand_b['id']}", headers=headers)
    assert res_sel.status_code == 200
    print(f"    Step C: Selected candidate {cand_b['revision_label']}")
    
    # Step D: Save Candidate B as a persistent Saved Recipe
    save_payload = {
        "recipe_name": f"Multi-Gen Saved B - {uuid.uuid4().hex[:6]}",
        "recipe_data": cand_b["recipe_data"],
        "target_properties": [{"name": "Mooney", "target": "49"}],
        "competitor_properties": [],
        "recipe_kind": "OPTIMIZED",
        "parent_recipe_id": test_recipe_normal["id"],
        "source_trial_id": trial1_id,
        "source_optimized_id": cand_b["id"]
    }
    res_save = requests.post(f"{BASE_URL}/recipe/saved", json=save_payload, headers=headers)
    assert res_save.status_code == 201, f"Failed to save recipe: {res_save.text}"
    saved_b = res_save.json()["data"]
    saved_b_id = saved_b["id"]
    print(f"    Step D: Saved Candidate B as persistent recipe: ID = {saved_b_id}")
    print(f"            parent_recipe_id = {saved_b['parent_recipe_id']}")
    print(f"            source_trial_id  = {saved_b['source_trial_id']}")
    assert saved_b["parent_recipe_id"] == str(test_recipe_normal["id"])
    assert saved_b["source_trial_id"] == str(trial1_id)
    
    # Step E: Create Customer Trial #2 from Saved Candidate B
    p6_trial2 = {
        "saved_recipe_id": saved_b_id,
        "feedback_text": "Second-generation feedback on saved candidate B",
        "target_values": {"Mooney Viscosity": "47"}
    }
    res_trial2 = requests.post(f"{BASE_URL}/recipe/trials", json=p6_trial2, headers=headers)
    assert res_trial2.status_code == 200
    t6_2 = res_trial2.json()["data"]
    trial2_id = t6_2["id"]
    print(f"    Step E: Created Customer Trial #2 from Recipe B: ID = {trial2_id}")
    assert t6_2["saved_recipe_id"] == str(saved_b_id)
    assert t6_2["recipe_snapshot"]["parent_recipe_id"] == str(test_recipe_normal["id"])
    print(f"            Snapshot parent_recipe_id = {t6_2['recipe_snapshot']['parent_recipe_id']}")
    print("--> TEST 6 PASSED!")
    
    print("\n================== ALL TESTS PASSED SUCCESSFULLY! ==================\n")

if __name__ == "__main__":
    test_live_customer_trials()
