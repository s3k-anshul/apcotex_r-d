import httpx
import asyncio

async def main():
    # 1. Login to get token
    print("Logging in...")
    async with httpx.AsyncClient() as client:
        res = await client.post("http://localhost:8000/api/v1/auth/login", json={"username": "admin", "password": "Admin@123!"})
        if res.status_code != 200:
            print(f"Login failed: {res.text}")
            return
        token = res.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # 2. Get latest runs
        print("\nFetching latest runs...")
        runs_res = await client.get("http://localhost:8000/api/v1/research-runs", headers=headers)
        runs = runs_res.json()["data"]["items"]
        
        completed_run = None
        for r in runs:
            if r["status"] == "COMPLETED":
                completed_run = r
                break
                
        if not completed_run:
            print("No completed runs found.")
            return
            
        print(f"Found completed run: {completed_run['id']} for {completed_run['compound_name']}")
        
        # 3. Fetch report
        print(f"\nFetching report for {completed_run['id']}...")
        report_res = await client.get(f"http://localhost:8000/api/v1/research-runs/{completed_run['id']}/report", headers=headers)
        report_data = report_res.json()["data"]
        
        print("\n--- REPORT DATA KEYS ---")
        print(list(report_data.keys()))
        
        sr = report_data.get("structuredReport", {})
        print("\n--- STRUCTURED REPORT KEYS ---")
        print(list(sr.keys()))
        
        if 'methodology_patents' in sr:
            print(f"\nmethodology_patents length: {len(sr['methodology_patents'])}")
            if sr['methodology_patents']:
                print("\nFirst patent keys:")
                print(list(sr['methodology_patents'][0].keys()))
        elif 'primary_patents' in sr:
            print(f"\nprimary_patents length: {len(sr['primary_patents'])}")

if __name__ == "__main__":
    asyncio.run(main())
