import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine('postgresql+asyncpg://postgres:Anshul%402005@localhost:5432/apcotex_db')
    async with engine.begin() as conn:
        res = await conn.execute(text('SELECT COUNT(*) FROM patent_documents'))
        print('Patent count in DB:', res.scalar())
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
