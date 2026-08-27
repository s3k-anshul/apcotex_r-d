import asyncio
import os
import sys
import logging
import uuid
from datetime import datetime, timezone

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.db.session import AsyncSessionLocal
from app.models.research_run import ResearchRun, RunStatus
from app.services.pipeline.orchestrator import PipelineOrchestrator

# Force logging to output to console for the test
logging.basicConfig(level=logging.INFO, format="%(message)s")

tests = [
    {"name": "Test A", "input": "Low Acrylonitrile NBR", "jurisdictions": ["US"]},
    {"name": "Test B", "input": "High Acrylonitrile NBR", "jurisdictions": ["US"]},
    {"name": "Test C", "input": "Generic NBR", "jurisdictions": ["US"]},
    {"name": "Test D", "input": "Polycarbonate", "jurisdictions": ["US"]},
]

async def main():
    for idx, test in enumerate(tests):
        print(f"\n============================================================")
        print(f"STARTING TEST: {test['name']} - {test['input']}")
        print(f"============================================================")
        
        from app.models.user import User
        from sqlalchemy import select
        
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(User).limit(1))
            user = result.scalars().first()
            if not user:
                user = User(
                    id=uuid.uuid4(),
                    email=f"test_{uuid.uuid4()}@example.com",
                    name="Test User",
                    password_hash="dummy"
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
            
            # Create a mock run
            run = ResearchRun(
                compound_name=test["input"],
                jurisdictions=test["jurisdictions"],
                status=RunStatus.PENDING,
                competitors=[],
                mentioned_websites=[],
                created_by=user.id
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            
            orchestrator = PipelineOrchestrator(run.id)
            
            try:
                result = await orchestrator.execute()
                print(f"Result for {test['name']}: {result}")
            except Exception as e:
                print(f"Error in {test['name']}: {e}")
                
        print(f"\n============================================================")
        print(f"FINISHED TEST: {test['name']}")
        print(f"============================================================\n")

if __name__ == "__main__":
    asyncio.run(main())

if __name__ == "__main__":
    asyncio.run(main())
