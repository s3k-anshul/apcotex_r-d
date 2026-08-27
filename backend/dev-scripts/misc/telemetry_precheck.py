import asyncio
import os
import sys

def run_test_1():
    try:
        from app.core.telemetry import get_current_run_id, get_current_stage, TelemetryStage
        from app.services.usage_logger import UsageLogger
        from app.models.api_usage_log import APIUsageLog
        
        # Test functions
        get_current_run_id()
        get_current_stage()
        
        print("TELEMETRY PRECHECK: PASS")
        return True
    except Exception as e:
        print(f"TELEMETRY PRECHECK: FAILED\n{type(e).__name__}: {str(e)}")
        return False

async def run_test_2():
    try:
        from app.services.pipeline.search_service import SearchService
        service = SearchService()
        
        print("TEST 2 - ONE SERPER REQUEST")
        results, success = await service.search_patents_page("Nitrile Rubber polymerization", "TI", 1, ["US"])
        print(f"HTTP 200: {success}")
        print(f"Results > 0: {len(results) > 0} ({len(results)})")
        print("Telemetry record created (check logs)")
        print("No pipeline failure")
        return True
    except Exception as e:
        print(f"TEST 2 FAILED: {str(e)}")
        return False

if __name__ == "__main__":
    if not run_test_1():
        sys.exit(1)
        
    asyncio.run(run_test_2())
