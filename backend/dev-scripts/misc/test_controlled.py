import asyncio
import os
import sys
import logging

os.environ["DRY_RUN_LLM"] = "false"
os.environ["PRIMARY_PATENT_TARGET"] = "3"

logging.basicConfig(level=logging.INFO, format='%(message)s')

# Set path so we can import app modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.session import AsyncSessionLocal
from app.models.research_run import ResearchRun, RunStatus
from app.models.user import User
from app.services.pipeline.orchestrator import PipelineOrchestrator

async def main():
    print("="*60)
    print("Running CONTROLLED TEST: Query Expansion -> Selection")
    print("="*60)
    
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if not user:
            print("No user found")
            return
            
        run = ResearchRun(
            compound_name="Low Acrylonitrile NBR",
            competitors=["Zeon"],
            selected_sources=["google_patents"],
            jurisdictions=["US"],
            status=RunStatus.PENDING,
            created_by=user.id,
            report_version=1
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        print(f"Created run {run.id}")
        
    orchestrator = PipelineOrchestrator(run.id)
    
    # We just run the orchestrator, we can see logs
    await orchestrator.execute()
    
    async with AsyncSessionLocal() as session:
        r = await session.get(ResearchRun, run.id)
        print(f"\nRun finished with status: {r.status}")
        
if __name__ == "__main__":
    asyncio.run(main())
