import asyncio
import httpx
import urllib.parse
from pprint import pprint

async def test_gp():
    query = 'Low Acrylonitrile "nitrile butadiene rubber" polymerization'
    page = 1
    
    # 1. XHR Endpoint
    q_encoded = urllib.parse.quote(f"q={query}&page={page}")
    xhr_url = f"https://patents.google.com/xhr/query?url={q_encoded}&exp="
    
    # 2. Standard Search Page
    q_encoded_std = urllib.parse.quote(query)
    std_url = f"https://patents.google.com/?q={q_encoded_std}&page={page}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive"
    }
    
    print(f"XHR URL: {xhr_url}")
    print(f"STD URL: {std_url}")
    
    async with httpx.AsyncClient(headers=headers) as client:
        # Test XHR
        try:
            print("\n--- XHR REQUEST ---")
            r_xhr = await client.get(xhr_url)
            print(f"Status: {r_xhr.status_code}")
            print("Headers:")
            pprint(dict(r_xhr.headers))
            content = r_xhr.text
            print(f"Content-Type: {r_xhr.headers.get('content-type')}")
            print(f"Body snippet:\n{content[:500]}")
        except Exception as e:
            print(f"XHR Error: {e}")
            
        # Test Standard HTML
        try:
            print("\n--- STD REQUEST ---")
            r_std = await client.get(std_url)
            print(f"Status: {r_std.status_code}")
            print("Headers:")
            pprint(dict(r_std.headers))
            content = r_std.text
            print(f"Content-Type: {r_std.headers.get('content-type')}")
            print(f"Body snippet:\n{content[:500]}")
        except Exception as e:
            print(f"STD Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_gp())
