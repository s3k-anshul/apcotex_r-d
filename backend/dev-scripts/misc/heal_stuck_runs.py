"""Mark stuck active research runs as CANCELLED, then optionally print status."""
import asyncio
import sys
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.db.database import engine
from app.models.research_run import ResearchRun, RunStatus

RUN_IDS = sys.argv[1:]


async def main():
    async with AsyncSession(engine, expire_on_commit=False) as session:
        if RUN_IDS:
            q = select(ResearchRun).where(ResearchRun.id.in_(RUN_IDS))
        else:
            q = select(ResearchRun).where(ResearchRun.status.in_(list(RunStatus.active_states())))
        rows = (await session.execute(q)).scalars().all()
        for run in rows:
            print(f"BEFORE {run.id} {run.compound_name} {run.status}")
            if run.status in RunStatus.active_states():
                run.status = RunStatus.CANCELLED
                print(f"  -> CANCELLED")
        await session.commit()
        print(f"healed={len(rows)}")


if __name__ == "__main__":
    asyncio.run(main())
