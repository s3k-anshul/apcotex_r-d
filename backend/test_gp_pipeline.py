import asyncio
import os
import sys

from app.services.pipeline.orchestrator import ResearchOrchestrator
from app.services.db.session import AsyncSessionLocal
from app.core.config import settings

async def main():
    settings.PATENT_SEARCH_PROVIDER = "google_patents"
    # Use NBR (Nitrile Butadiene Rubber)
    orchestrator = ResearchOrchestrator(run_id="test_gp_fix")
    
    async with AsyncSessionLocal() as session:
        # We will mock the database interactions just to run the query building and search loop
        try:
            print("Running test orchestration...")
            await orchestrator.execute(session)
        except Exception as e:
            print(f"Exception during execute: {e}")

if __name__ == "__main__":
    asyncio.run(main())
