import asyncio
import os
import sys
from uuid import uuid4
from datetime import datetime, timezone
import json

# Add backend to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import engine
from app.models.research_run import ResearchRun, RunStatus
from app.services.pipeline.orchestrator import PipelineOrchestrator, get_background_session

async def main():
    run_id = uuid4()
    
    async with AsyncSession(engine) as session:
        from app.models.user import User
        user_id = uuid4()
        user = User(
            id=user_id,
            username=f"test_{user_id}",
            full_name="Test User",
            email=f"test_{user_id}@example.com",
            hashed_password="mock",
            is_active=True
        )
        session.add(user)
        await session.flush()
        
        # Create a mock run
        run = ResearchRun(
            id=run_id,
            compound_name="High Acrylonitrile NBR",
            jurisdictions=["US", "EP"],
            publication_filter={}, # Any Time
            status=RunStatus.PENDING,
            report_version=1,
            created_by=user_id
        )
        session.add(run)
        await session.commit()
        
    print(f"Created run {run_id}. Starting pipeline...")
    
    orchestrator = PipelineOrchestrator(run_id)
    await orchestrator.execute()
    
    print("Pipeline execution finished.")
    
    # Check DB
    async with AsyncSession(engine) as session:
        from sqlalchemy.future import select
        from app.models.report_metadata import ReportMetadata
        from app.models.report_file import ReportFile
        
        result = await session.execute(select(ResearchRun).where(ResearchRun.id == run_id))
        run = result.scalar_one_or_none()
        print(f"Final Status: {run.status}")
        
        if run.status == RunStatus.COMPLETED:
            meta_res = await session.execute(select(ReportMetadata).where(ReportMetadata.research_run_id == run_id))
            meta = meta_res.scalar_one_or_none()
            if meta:
                print(f"Report Generated: {meta.title} (Sources: {meta.source_count})")
                
                files_res = await session.execute(select(ReportFile).where(ReportFile.report_metadata_id == meta.id))
                for f in files_res.scalars().all():
                    print(f" - {f.file_type}: {f.file_path}")
            else:
                print("Error: COMPLETED but no metadata found.")
        elif run.status == RunStatus.FAILED:
            print(f"Failed. Run status is {run.status}")

if __name__ == "__main__":
    asyncio.run(main())
