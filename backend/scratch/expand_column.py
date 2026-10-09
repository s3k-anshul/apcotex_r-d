import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from app.db.session import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(text("ALTER TABLE recipe_candidates ALTER COLUMN name TYPE VARCHAR(255);"))
            await session.commit()
            print("Successfully expanded recipe_candidates.name column to VARCHAR(255)")
        except Exception as e:
            print(f"Error altering table: {e}")

if __name__ == "__main__":
    asyncio.run(main())
