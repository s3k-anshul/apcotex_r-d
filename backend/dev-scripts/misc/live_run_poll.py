"""Trigger a live research run and poll until terminal status."""
import asyncio
import sys
import httpx

COMPOUND = sys.argv[1] if len(sys.argv) > 1 else "Low Acrylonitrile NBR"
BASE = "http://127.0.0.1:8000"


async def main():
    async with httpx.AsyncClient(timeout=60.0) as client:
        res = await client.post(
            f"{BASE}/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        res.raise_for_status()
        token = res.json()["data"]["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        payload = {
            "compound_name": COMPOUND,
            "competitors": [],
            "patent_sources": ["google_patents"],
            "mentioned_websites": [],
            "jurisdictions": ["US", "EP"],
            "polymerization_medium": "any",
        }
        res = await client.post(
            f"{BASE}/api/v1/research-runs", json=payload, headers=headers
        )
        print("CREATE", res.status_code, res.text[:500])
        res.raise_for_status()
        run_id = res.json()["data"]["id"]
        print("RUN_ID", run_id)

        while True:
            poll = await client.get(
                f"{BASE}/api/v1/research-runs/{run_id}", headers=headers
            )
            data = poll.json()["data"]
            status = data["status"]
            print("STATUS", status)
            if status in (
                "COMPLETED",
                "COMPLETED_PARTIAL",
                "FAILED",
                "CANCELLED",
                "LLM_PROVIDER_EXHAUSTED",
            ):
                print("FINAL", status)
                print("ERROR", data.get("error_message"))
                print("SOURCE_COUNT_HINT", data)
                break
            await asyncio.sleep(15)


if __name__ == "__main__":
    asyncio.run(main())
