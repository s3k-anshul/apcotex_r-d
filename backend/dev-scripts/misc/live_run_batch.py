"""Run multiple live compounds sequentially and print run IDs."""
import asyncio
import sys
import httpx

COMPOUNDS = sys.argv[1:] or [
    "Low Acrylonitrile NBR",
    "NBR",
    "Low-Styrene SBR",
    "HNBR",
]
BASE = "http://127.0.0.1:8000"


async def run_one(client, headers, compound: str) -> dict:
    payload = {
        "compound_name": compound,
        "competitors": [],
        "patent_sources": ["google_patents"],
        "mentioned_websites": [],
        "jurisdictions": ["US", "EP"],
        "polymerization_medium": "any",
    }
    res = await client.post(f"{BASE}/api/v1/research-runs", json=payload, headers=headers)
    print("CREATE", compound, res.status_code)
    res.raise_for_status()
    run_id = res.json()["data"]["id"]
    print("RUN_ID", compound, run_id)
    while True:
        poll = await client.get(f"{BASE}/api/v1/research-runs/{run_id}", headers=headers)
        data = poll.json()["data"]
        status = data["status"]
        print("STATUS", compound, status)
        if status in (
            "COMPLETED",
            "COMPLETED_PARTIAL",
            "FAILED",
            "CANCELLED",
            "LLM_PROVIDER_EXHAUSTED",
        ):
            print("FINAL", compound, status, "error=", data.get("error_message"))
            return {"compound": compound, "id": run_id, "status": status, "error": data.get("error_message")}
        await asyncio.sleep(15)


async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.post(
            f"{BASE}/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        res.raise_for_status()
        token = res.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        results = []
        for compound in COMPOUNDS:
            results.append(await run_one(client, headers, compound))
        print("ALL_DONE", results)


if __name__ == "__main__":
    asyncio.run(main())
