import asyncio
import os
import sys
import logging

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.INFO, format="%(message)s")

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.models.research_run import ResearchRun, RunStatus

async def main():
    from sqlalchemy import text
    import uuid
    async with AsyncSessionLocal() as session:
        # Get first user
        res = await session.execute(text("SELECT id FROM users LIMIT 1"))
        user_id = res.scalar()
        if not user_id:
            user_id = uuid.uuid4()
            await session.execute(text(f"INSERT INTO users (id, email) VALUES ('{user_id}', 'test@example.com')"))
            
        run = ResearchRun(
            compound_name="Low Acrylonitrile NBR",
            created_by=user_id,
            status=RunStatus.PENDING,
            jurisdictions=["US", "EP"],
            publication_filter={"date_filter": "Any Time"}
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        
        print(f"Created run {run.id}. Starting orchestrator...")
        
        orch = PipelineOrchestrator(run.id)
        await orch.execute()
        
        await session.refresh(run)
        print(f"Run ended with status: {run.status}")

if __name__ == "__main__":
    asyncio.run(main())
