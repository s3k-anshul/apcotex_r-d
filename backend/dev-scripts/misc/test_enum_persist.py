import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.database import engine
from app.models.research_run import ResearchRun, RunStatus

async def test_enum():
    async with AsyncSession(engine, expire_on_commit=False) as session:
        result = await session.execute(select(ResearchRun).limit(1))
        run = result.scalar_one_or_none()
        
        if run:
            print(f"Found run {run.id}, updating status to COMPLETED_PARTIAL...")
            run.status = RunStatus.COMPLETED_PARTIAL
            await session.commit()
            print("Successfully committed COMPLETED_PARTIAL to the database!")
        else:
            print("No runs found in the database to test.")

if __name__ == "__main__":
    asyncio.run(test_enum())
