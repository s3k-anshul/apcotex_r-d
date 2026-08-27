import asyncio
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from app.db.session import AsyncSessionLocal
from sqlalchemy import select, func
from app.models.api_usage_log import APIUsageLog

async def check_telemetry():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(APIUsageLog).order_by(APIUsageLog.created_at.desc()))
        logs = result.scalars().all()
        
        print(f"Total API Usage Logs: {len(logs)}")
        for log in logs[:10]:
            print(f"[{log.status}] Stage: {log.stage}, Provider: {log.provider}, Operation: {log.operation}, Retries: {log.retry_count}, Tokens: {log.total_tokens}, Cost: {log.estimated_cost}")

if __name__ == "__main__":
    asyncio.run(check_telemetry())
