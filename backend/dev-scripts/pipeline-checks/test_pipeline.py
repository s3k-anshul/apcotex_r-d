import asyncio
import os
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import engine
from app.models.research_run import ResearchRun, RunStatus
from app.services.pipeline.orchestrator import PipelineOrchestrator

async def test_run():
    async with AsyncSession(engine, expire_on_commit=False) as session:
        # Get an existing user
        from sqlalchemy import text
        result = await session.execute(text("SELECT id FROM users LIMIT 1"))
        user_id = result.scalar()
        if not user_id:
            user_id = uuid.uuid4()
            await session.execute(text(f"INSERT INTO users (id, email, password_hash) VALUES ('{user_id}', 'test@test.com', 'hash')"))
            await session.commit()
            
        # Create a new run
        run = ResearchRun(
            compound_name="Acetylsalicylic acid",
            status=RunStatus.PENDING,
            jurisdictions=["US", "EP"],
            created_by=user_id,
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        
        print(f"Created run {run.id}, starting Orchestrator...")
        
    orchestrator = PipelineOrchestrator(run.id)
    await orchestrator.execute()
    
    async with AsyncSession(engine, expire_on_commit=False) as session:
        run_after = await session.get(ResearchRun, run.id)
        print(f"Finished. Final status: {run_after.status}")

if __name__ == "__main__":
    asyncio.run(test_run())
