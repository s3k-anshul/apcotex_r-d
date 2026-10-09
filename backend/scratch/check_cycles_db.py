import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import AsyncSessionLocal
from app.models.recipe_cycle import RecipeCycle
from app.models.report_metadata import ReportMetadata
from sqlalchemy import select

from sqlalchemy.orm import selectinload

async def main():
    async with AsyncSessionLocal() as session:
        # Check all recipe cycles
        stmt = (
            select(RecipeCycle)
            .options(selectinload(RecipeCycle.candidates))
            .order_by(RecipeCycle.created_at.desc())
            .limit(10)
        )
        res = await session.execute(stmt)
        cycles = res.scalars().all()
        print(f"=== FOUND {len(cycles)} RECIPE CYCLES ===")
        for c in cycles:
            print(f"Cycle ID: {c.id}")
            print(f"  Compound: {c.compound_name}")
            print(f"  Status: {c.status}")
            print(f"  Target Properties: {c.target_properties}")
            print(f"  Candidates count: {len(c.candidates) if c.candidates else 0}")
            if c.candidates:
                for cand in c.candidates[:2]:
                    print(f"    Candidate: {cand.name}")
                    if cand.recipe_data:
                        pred = cand.recipe_data.get('predicted_properties')
                        print(f"      pred_props sample: {pred[:2] if pred else 'None'}")
            print("-" * 50)

if __name__ == "__main__":
    asyncio.run(main())
