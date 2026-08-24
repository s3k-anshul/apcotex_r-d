import asyncio
import json
import httpx
from app.core.config import settings

async def main():
    query = "US method for manufacturing Acrylonitrile Butadiene Rubber patent"
    payload = json.dumps({"q": query, "num": 3})
    headers = {
        'X-API-KEY': settings.SERPER_API_KEY,
        'Content-Type': 'application/json'
    }
    async with httpx.AsyncClient() as client:
        response = await client.post("https://google.serper.dev/search", headers=headers, data=payload)
        print(json.dumps(response.json(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
