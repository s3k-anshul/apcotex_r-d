import urllib.parse
import httpx
import asyncio

async def test_gp():
    query = 'Low Acrylonitrile "nitrile butadiene rubber" polymerization'
    page = 1
    
    # Correct browser encoding simulation
    # 1. inner query params are quote_plus'd
    q_encoded = urllib.parse.quote_plus(query)
    inner_query = f"q={q_encoded}&page={page}"
    
    # 2. the whole string "q=...&page=1" is passed to url=
    # So we urlencode it. The '=' becomes %3D, the '&' becomes %26.
    encoded_inner = urllib.parse.quote(inner_query)
    
    url = f"https://patents.google.com/xhr/query?url={encoded_inner}&exp="
    
    print(f"Constructed URL: {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://patents.google.com/",
        "Connection": "keep-alive"
    }
    
    async with httpx.AsyncClient(headers=headers) as client:
        try:
            r = await client.get(url)
            print(f"Status: {r.status_code}")
            if r.status_code == 200:
                print(f"Results parsed: {len(r.json().get('results', {}).get('cluster', []))}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_gp())
