import asyncio
from app.services.pipeline.compound_intelligence import CompoundIntelligenceService
from app.services.pipeline.cache_service import CacheService

async def test_run():
    cache_service = CacheService()
    cis = CompoundIntelligenceService(cache_service)
    print("Testing CompoundSearchProfile generation for 'Low Acrylonitrile NBR'...")
    profile = await cis.generate_profile("Low Acrylonitrile NBR")
    if profile:
        print("Success!")
        print("Monomers:", profile.major_monomers)
        print(f"Generated {len(profile.search_queries)} search queries.")
    else:
        print("Failed to generate profile.")

if __name__ == "__main__":
    asyncio.run(test_run())
