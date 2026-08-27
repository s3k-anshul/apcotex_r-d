import asyncio
import httpx

async def main():
    url = 'https://google.serper.dev/search'
    q = '(("low acrylonitrile" OR "low nitrile" OR "low bound acrylonitrile") AND ("nitrile butadiene rubber" OR "acrylonitrile butadiene copolymer" OR "NBR")) AND (polymerization OR polymerisation) AND NOT (glove* OR hose* OR "compounding recipe*") site:patents.google.com'
    payload = {'q': q}
    headers = {
      'X-API-KEY': '3d4a5ad1e2b4f59b6f923f0f80196aa59a388acb',
      'Content-Type': 'application/json'
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers)
        print('Status:', response.status_code)
        print('Text:', response.text)

asyncio.run(main())
