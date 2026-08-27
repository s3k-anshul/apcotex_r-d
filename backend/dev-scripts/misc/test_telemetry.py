import asyncio
import sys
import os
import uuid
import time
from fastapi.testclient import TestClient

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.services.usage_logger import UsageLogger
from app.core.telemetry import set_current_run_id, set_current_stage, TelemetryStage
from app.main import app

async def test_logging():
    run_id = uuid.uuid4()
    set_current_run_id(run_id)
    set_current_stage(TelemetryStage.QUERY_EXPANSION)
    
    # 1. Log a success
    print("Logging success...")
    await UsageLogger._async_record_usage(
        provider="gemini",
        operation="generate_structured",
        model="gemini-1.5-flash",
        input_tokens=1000,
        output_tokens=500,
        request_count=1,
        latency_ms=1200,
        status="success"
    )
    
    # 2. Log a failure
    print("Logging failure...")
    await UsageLogger._async_record_usage(
        provider="serper",
        operation="google_patents_search",
        latency_ms=300,
        status="failed",
        error_type="HTTPStatusError",
        error_message="Credits exhausted"
    )
    
    # Wait a bit to ensure async writes complete (not really needed since we called _async_record_usage directly)
    
    # 3. Test API endpoints (By querying DB directly to avoid FastAPI test client async loop issues)
    print("Testing DB inserts...")
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import select, func
    from app.models.api_usage_log import APIUsageLog
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                func.sum(APIUsageLog.estimated_cost).label("total_cost"),
                func.sum(APIUsageLog.total_tokens).label("total_tokens"),
                func.count().label("total_requests")
            ).where(APIUsageLog.research_run_id == run_id)
        )
        row = result.first()
        print("\n--- DB Summary ---")
        print(f"Total Requests: {row.total_requests}")
        print(f"Total Tokens: {row.total_tokens}")
        print(f"Total Cost: ${row.total_cost:.5f}")
        
        result2 = await session.execute(
            select(APIUsageLog.stage, func.count().label("c")).where(APIUsageLog.research_run_id == run_id).group_by(APIUsageLog.stage)
        )
        print("\n--- DB Stages ---")
        for r in result2.all():
            print(f"Stage: {r.stage}, Requests: {r.c}")

if __name__ == "__main__":
    asyncio.run(test_logging())
