import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.pipeline.search_service import SearchService

async def main():
    service = SearchService()
    
    compounds = [
        "Low Acrylonitrile NBR",
        "High Acrylonitrile NBR",
        "Polycarbonate"
    ]
    
    for compound in compounds:
        print(f"\n{'='*50}\nTESTING: {compound}\n{'='*50}")
        try:
            result = await service.generate_strategy(compound_name=compound)
            print(f"Base Material: {result.target_material}")
            print(f"Target Attribute: {', '.join(result.requested_attributes)}")
            print("Queries:")
            for i, q in enumerate(result.search_queries):
                print(f"  {i+1:02d}. {q}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
