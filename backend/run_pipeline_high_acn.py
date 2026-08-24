import asyncio, logging
from app.db.session import AsyncSessionLocal
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.models.research_run import ResearchRun

logging.basicConfig(level=logging.INFO)

async def main():
    async with AsyncSessionLocal() as session:
        import uuid
        from sqlalchemy import text
        result = await session.execute(text("SELECT id FROM users LIMIT 1"))
        user_id = result.scalar_one_or_none()
        run = ResearchRun(
            compound_name="High Acrylonitrile NBR",
            jurisdictions=["US", "EP"],
            publication_filter={"year_from": "2010", "year_to": "2024"},
            created_by=user_id if user_id else uuid.uuid4()
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        print(f"Starting pipeline for High Acrylonitrile NBR, run_id: {run.id}")
        await PipelineOrchestrator(run.id).execute()
        print(f"Completed: {run.status}")

if __name__ == "__main__":
    asyncio.run(main())
