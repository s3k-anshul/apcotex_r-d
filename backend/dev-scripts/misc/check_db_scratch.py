import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def get_enums():
    engine = create_async_engine('postgresql+asyncpg://postgres:Anshul%402005@localhost:5432/apcotex_db')
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT enumlabel FROM pg_enum JOIN pg_type ON pg_enum.enumtypid = pg_type.oid WHERE typname = 'runstatus';"))
        print([row[0] for row in res.fetchall()])

if __name__ == '__main__':
    asyncio.run(get_enums())
