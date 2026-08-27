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
    settings.PATENT_SEARCH_PROVIDER = "google_patents"
    
    # Simple profile
    profile_data = {
        "compound": "Nitrile Butadiene Rubber",
        "compound_name": "NBR",
        "target_attributes": [],
        "base_chemistry": "Nitrile Butadiene Rubber",
        "synonyms": ["NBR"],
        "abbreviations": ["NBR"]
    }
    
    from sqlalchemy import text
    import uuid
    async with AsyncSessionLocal() as session:
        # Get first user
        res = await session.execute(text("SELECT id FROM users LIMIT 1"))
        user_id = res.scalar()
        if not user_id:
            user_id = uuid.uuid4()
            await session.execute(text(f"INSERT INTO users (id, email) VALUES ('{user_id}', 'test@example.com')"))
            
        # Create dummy run
        run = ResearchRun(
            compound_name="NBR",
            created_by=user_id,
            status=RunStatus.PENDING
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        
        print(f"Created run {run.id}. Starting orchestrator...")
        
        orch = PipelineOrchestrator(run.id)
        # Inject the profile manually
        from app.services.pipeline.schemas import CompoundSearchProfile
        profile = CompoundSearchProfile(**profile_data)
        
        orch.profile = profile
        
        await orch.execute()
        
        await session.refresh(run)
        print(f"Run ended with status: {run.status}")

if __name__ == "__main__":
    asyncio.run(main())
