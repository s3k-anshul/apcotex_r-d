import asyncio
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.db.session import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM app_config WHERE key = 'active_llm_provider';"))
        await session.commit()
        print("Deleted active_llm_provider from DB.")

if __name__ == "__main__":
    asyncio.run(main())
