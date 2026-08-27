import asyncio
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.db.session import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT key, value FROM app_configs WHERE key = 'active_llm_provider'"))
        for row in result:
            print(f"DB CONFIG: {row.key} = {row.value}")

if __name__ == "__main__":
    asyncio.run(main())
