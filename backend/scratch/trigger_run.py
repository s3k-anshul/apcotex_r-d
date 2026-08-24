import httpx
import asyncio
import time

async def main():
    print("Logging in...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post("http://localhost:8000/api/v1/auth/login", json={"username": "admin", "password": "Admin@123!"})
        if res.status_code != 200:
            print(f"Login failed: {res.text}")
            return
        token = res.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        print("Creating run...")
        payload = {
            "compound_name": "High Acrylonitrile NBR",
            "competitors": [],
            "patent_sources": ["google_patents"],
            "mentioned_websites": [],
            "jurisdictions": ["US", "EP"]
        }
        res = await client.post("http://localhost:8000/api/v1/research-runs", json=payload, headers=headers)
        if res.status_code != 201:
            print(f"Run creation failed: {res.text}")
            return
        
        run_data = res.json()["data"]
        run_id = run_data["id"]
        print(f"Run created: {run_id}")
        
        print("Polling...")
        while True:
            poll = await client.get(f"http://localhost:8000/api/v1/research-runs/{run_id}", headers=headers)
            status = poll.json()["data"]["status"]
            print(f"Status: {status}")
            if status in ["COMPLETED", "COMPLETED_PARTIAL", "FAILED", "CANCELLED", "LLM_PROVIDER_EXHAUSTED"]:
                break
            await asyncio.sleep(5)
            
        if status != "COMPLETED" and status != "COMPLETED_PARTIAL":
            print("Run did not complete successfully.")
            return
            
        print(f"\nFetching report for {run_id}...")
        report_res = await client.get(f"http://localhost:8000/api/v1/research-runs/{run_id}/report", headers=headers)
        report_data = report_res.json()["data"]
        
        sr = report_data.get("structuredReport", {})
        print("\n--- STRUCTURED REPORT KEYS ---")
        print(list(sr.keys()))
        
        if 'methodology_patents' in sr:
            print(f"\nmethodology_patents length: {len(sr['methodology_patents'])}")
        elif 'primary_patents' in sr:
            print(f"\nprimary_patents length: {len(sr['primary_patents'])}")

if __name__ == "__main__":
    asyncio.run(main())
