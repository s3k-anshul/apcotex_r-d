import asyncio
from sqlalchemy import text
from app.db.database import engine

async def get_enums():
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT enumlabel FROM pg_enum WHERE enumtypid = 'runstatus'::regtype ORDER BY enumsortorder;"))
        for row in result:
            print(row[0])

asyncio.run(get_enums())
