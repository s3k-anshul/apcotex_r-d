import asyncio
import logging
import os
import sys

# Setup path so we can import 'app'
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.pipeline.compound_intelligence import CompoundIntelligenceService
from app.services.pipeline.cache_service import PipelineCacheService

logging.basicConfig(level=logging.INFO, format="%(message)s")

async def test():
    cache = PipelineCacheService(None, "test-run")
    service = CompoundIntelligenceService(cache)
    
    profile = await service.generate_profile("High Acrylonitrile NBR")
    
    print("\n--- DERIVED INTERNAL PROFILE ---")
    print(profile.model_dump_json(indent=2))

if __name__ == "__main__":
    asyncio.run(test())
