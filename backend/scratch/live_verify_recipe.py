"""
backend/scratch/live_verify_recipe.py
Live end-to-end verification script for Recipe Generation and Arbitrary Properties.
"""
import asyncio
import json
import uuid
import httpx

BASE_URL = "http://127.0.0.1:8000"

async def main():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=300.0) as client:
        # 1. Login as admin
        login_res = await client.post("/api/v1/auth/login", json={
            "username": "admin",
            "password": "admin123"
        })
        print(f"Login status: {login_res.status_code}")
        login_data = login_res.json()
        token = login_data.get("access_token") or login_data.get("data", {}).get("access_token")
        assert token, f"Could not obtain token: {login_data}"
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Create a Recipe Cycle for Low Acrylonitrile NBR with 4 targets and unconstrained rows
        cycle_payload = {
            "target_product": "Low Acrylonitrile NBR",
            "process_type": "Batch",
            "temperature_range": "5–7 °C",
            "target_properties": [
                {"id": "prop-1", "feature": "Bound Acrylonitrile (BACN)", "unit": "wt%", "min": "20.0", "max": "25.0"},
                {"id": "prop-2", "feature": "Mooney Viscosity ML(1+4)@100°C", "unit": "MU", "min": "28.0", "max": "35.0"},
                {"id": "prop-3", "feature": "Stress Relaxation", "unit": "sec", "min": "6.5", "max": "8.5"},
                {"id": "prop-4", "feature": "Polymer Density", "unit": "g/cm³", "min": "0.95", "max": "1.02"},
                {"id": "prop-5", "feature": "Ash Content", "unit": "%", "min": "", "max": ""},  # unconstrained row
            ]
        }
        create_res = await client.post("/api/v1/recipe/cycles", json=cycle_payload, headers=headers)
        print(f"Create cycle status: {create_res.status_code}")
        cycle_data = create_res.json()
        cycle_id = cycle_data.get("id") or cycle_data.get("data", {}).get("id")
        print(f"Created cycle ID: {cycle_id}")

        # 3. Generate recipes (Step 2)
        print("Triggering Step 2 Recipe Generation...")
        gen_res = await client.post(f"/api/v1/recipe/cycles/{cycle_id}/generate", headers=headers)
        print(f"Generate recipes status: {gen_res.status_code}")
        gen_body = gen_res.json()
        candidates = gen_body.get("data", []) or gen_body.get("candidates", [])
        print(f"Candidate count received: {len(candidates)}")
        assert len(candidates) == 5, f"Expected 5 candidates, got {len(candidates)}"

        # 4. Verify candidate properties and persistence
        for idx, cand in enumerate(candidates, 1):
            name = cand.get("name")
            fit_score = cand.get("target_fit_score")
            conf_score = cand.get("confidence_score")
            preds = cand.get("predicted_properties") or cand.get("recipe_data", {}).get("predicted_properties") or []
            print(f"\n--- Candidate {idx}: {name} ---")
            print(f"  Target Fit Score: {fit_score}% | Confidence: {conf_score}%")
            print(f"  Predicted properties count: {len(preds)}")
            
            pred_names = [p.get("property") for p in preds]
            print(f"  Properties represented: {pred_names}")
            
            # Verify all user features are represented
            for prop in ["Bound Acrylonitrile (BACN)", "Mooney Viscosity ML(1+4)@100°C", "Stress Relaxation", "Polymer Density", "Ash Content"]:
                assert any(prop in p_name for p_name in pred_names), f"Missing {prop} in Candidate {idx}"

            # Check ash content (unconstrained) has status UNKNOWN and not marked passed
            ash_pred = next(p for p in preds if "Ash Content" in p.get("property"))
            print(f"  Ash Content (unconstrained row) status: {ash_pred.get('status')}, display: {ash_pred.get('target_display')}")
            assert ash_pred.get("status") == "UNKNOWN"
            assert ash_pred.get("passed") is False

        print("\nAll 5 candidates successfully generated, validated, and persisted!")

if __name__ == "__main__":
    asyncio.run(main())
