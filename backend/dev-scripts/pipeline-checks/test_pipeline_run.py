import asyncio
import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)

# Ensure backend is in path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.db.session import AsyncSessionLocal
from app.models.research_run import ResearchRun, RunStatus
from app.services.pipeline.orchestrator import PipelineOrchestrator

async def main():
    async with AsyncSessionLocal() as session:
        import uuid
        from sqlalchemy import text
        # Fetch an existing user id
        result = await session.execute(text("SELECT id FROM users LIMIT 1"))
        user_id = result.scalar()
        if not user_id:
            # Create a mock user
            user_id = uuid.uuid4()
            await session.execute(text("INSERT INTO users (id, email, hashed_password, is_active) VALUES (:id, :email, :pw, true)"), {"id": user_id, "email": "test@apcotex.com", "pw": "fake"})
            await session.commit()
            
        compound = sys.argv[1] if len(sys.argv) > 1 else "Low Acrylonitrile NBR"
        run = ResearchRun(
            compound_name=compound,
            created_by=user_id,
            status=RunStatus.PENDING,
            jurisdictions=["US", "EP"]
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        
        print(f"Created Research Run ID: {run.id}")
        
        orchestrator = PipelineOrchestrator(run.id)
        
        print("Starting orchestrator...")
        await orchestrator.execute()
        print(f"Orchestrator finished. Final status: {run.status}")

if __name__ == "__main__":
    asyncio.run(main())
