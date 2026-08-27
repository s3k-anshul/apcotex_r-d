import asyncio
import sys
from sqlalchemy import select, func, case
from app.db.session import AsyncSessionLocal
from app.models.api_usage_log import APIUsageLog

async def main():
    try:
        async with AsyncSessionLocal() as session:
            q = select(
                APIUsageLog.stage,
                func.coalesce(func.sum(case((APIUsageLog.provider.notin_(["serper", "serper.dev"]), APIUsageLog.request_count), else_=0)), 0).label("llm_calls"),
                func.coalesce(func.sum(case((APIUsageLog.provider.in_(["serper", "serper.dev"]), APIUsageLog.request_count), else_=0)), 0).label("serper_requests"),
                func.coalesce(func.sum(APIUsageLog.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(APIUsageLog.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(APIUsageLog.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(APIUsageLog.estimated_cost), 0).label("cost"),
                func.coalesce(func.avg(APIUsageLog.latency_ms), 0).label("avg_latency"),
                func.coalesce(func.sum(case((APIUsageLog.status == "failed", 1), else_=0)), 0).label("failures")
            ).group_by(APIUsageLog.stage)

            res = await session.execute(q)
            print(res.fetchall())
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
