import asyncio
import httpx
import urllib.parse
import time

async def test_session():
    queries = [
        "polymerization",
        "vulcanization",
        "coagulation"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://patents.google.com/",
        "Connection": "keep-alive"
    }

    # Use a single client with HTTP/2 support and cookies
    async with httpx.AsyncClient(headers=headers, http2=True, follow_redirects=True) as client:
        print("Fetching homepage to get cookies...")
        try:
            r0 = await client.get("https://patents.google.com/", timeout=10.0)
            print(f"Homepage status: {r0.status_code}")
        except Exception as e:
            print(f"Error getting homepage: {e}")
            
        # Wait a bit like a human
        await asyncio.sleep(2)
            
        for q in queries:
            page = 0
            query_encoded = urllib.parse.quote(q)
            url = f"https://patents.google.com/xhr/query?url=q%3D{query_encoded}%26page%3D{page}"
            
            print(f"\nTesting URL: {url}")
            try:
                res = await client.get(url, timeout=10.0)
                print(f"Status: {res.status_code}")
                if res.status_code == 200:
                    print("Success!")
                    data = res.json()
                    results = data.get("results", {}).get("cluster", [])
                    if results:
                        print(f"Found {len(results[0].get('result', []))} results")
                else:
                    print(res.text[:200])
            except Exception as e:
                print(f"Error: {e}")
            
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(test_session())
