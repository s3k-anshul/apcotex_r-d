import asyncio
import httpx
import urllib.parse

async def test_gp():
    formatted_query = '("nitrile butadiene rubber" OR "nitrile rubber" OR Buna-N) AND polymerization'
    page = 1
    gp_page = page - 1
    query_encoded = urllib.parse.quote(formatted_query)
    url = f"https://patents.google.com/xhr/query?url=q%3D{query_encoded}%26page%3D{gp_page}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://patents.google.com/"
    }

    print(f"Testing URL: {url}")
    
    # 1. Without headers
    print("\n--- Testing Without Headers ---")
    async with httpx.AsyncClient() as client:
        try:
            res = await client.get(url, timeout=10.0)
            print(f"Status: {res.status_code}")
            if res.status_code == 200:
                print("Success without headers!")
        except Exception as e:
            print(f"Error: {e}")

    # 2. With headers
    print("\n--- Testing With Headers ---")
    async with httpx.AsyncClient(headers=headers) as client:
        try:
            res = await client.get(url, timeout=10.0)
            print(f"Status: {res.status_code}")
            if res.status_code == 200:
                print("Success with headers!")
                data = res.json()
                results = data.get("results", {}).get("cluster", [])
                if results:
                    print(f"Found {len(results[0].get('result', []))} results")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_gp())
