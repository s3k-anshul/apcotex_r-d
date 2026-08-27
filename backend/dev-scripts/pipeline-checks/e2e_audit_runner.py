import asyncio
import os
import sys
import uuid
import logging

# Set up logging for the script to capture orchestrator output
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.db.session import AsyncSessionLocal
from app.models.research_run import ResearchRun, RunStatus
from app.services.pipeline.orchestrator import PipelineOrchestrator
from sqlalchemy import text

materials = [
    "Low Acrylonitrile NBR",
    "High Acrylonitrile NBR",
    "Generic NBR",
    "Polycarbonate",
    "Polyetheretherketone (PEEK)"
]

async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT id FROM users LIMIT 1"))
        user_id = result.scalar()
        if not user_id:
            user_id = uuid.uuid4()
            await session.execute(text("INSERT INTO users (id, email, hashed_password, is_active) VALUES (:id, :email, :pw, true)"), {"id": user_id, "email": "test@apcotex.com", "pw": "fake"})
            await session.commit()
            
    for material in materials:
        print(f"\n=================================================================")
        print(f"STARTING AUDIT PIPELINE FOR: {material}")
        print(f"=================================================================\n")
        
        async with AsyncSessionLocal() as session:
            run = ResearchRun(
                compound_name=material,
                created_by=user_id,
                status=RunStatus.PENDING,
                jurisdictions=["US", "EP"]
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            run_id = run.id
            
        print(f"Created Research Run ID: {run_id}")
        
        orchestrator = PipelineOrchestrator(run_id)
        
        print(f"Executing orchestrator for {material}...")
        try:
            await orchestrator.execute()
        except Exception as e:
            print(f"PIPELINE CRASHED FOR {material}: {e}")
            
        async with AsyncSessionLocal() as session:
            result = await session.execute(text(f"SELECT status FROM research_runs WHERE id = '{run_id}'"))
            status = result.scalar()
            print(f"Orchestrator finished. Final DB status: {status}\n")

if __name__ == "__main__":
    asyncio.run(main())
