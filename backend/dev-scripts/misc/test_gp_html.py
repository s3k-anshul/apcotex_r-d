import asyncio
import httpx
import urllib.parse
import re

async def test_html():
    formatted_query = '("nitrile butadiene rubber" OR "nitrile rubber" OR Buna-N) AND polymerization'
    page = 1
    query_encoded = urllib.parse.quote(formatted_query)
    
    # Just regular search page
    url = f"https://patents.google.com/?q={query_encoded}&page={page - 1}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://patents.google.com/"
    }

    print(f"Testing URL: {url}")
    
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        try:
            res = await client.get(url, timeout=10.0)
            print(f"Status: {res.status_code}")
            if res.status_code == 200:
                print("Success HTML request!")
                html = res.text
                
                # Check for patent IDs in HTML
                patent_ids = set(re.findall(r'patent/(.*?)/en', html))
                print(f"Found patents: {patent_ids}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_html())
