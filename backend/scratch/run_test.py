import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.pipeline.search_service import SearchService

async def main():
    service = SearchService()
    try:
        results, success = await service.search_patents_page("polymerization", "TITLE", 1)
        print("Success:", success)
        print("Results count:", len(results))
        for r in results[:2]:
            print("-", r["patent_number"], r["title"])
    except Exception as e:
        print("Caught Exception:", type(e).__name__, str(e))

if __name__ == "__main__":
    asyncio.run(main())
