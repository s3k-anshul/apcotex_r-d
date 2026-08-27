import httpx
import asyncio
import urllib.parse
from bs4 import BeautifulSoup
import re

async def test_normal_page():
    query = 'low acrylonitrile "nitrile butadiene rubber" polymerization'
    encoded_q = urllib.parse.quote(query)
    url = f"https://patents.google.com/?q={encoded_q}&page=0"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Connection": "keep-alive"
    }
    
    async with httpx.AsyncClient() as client:
        print(f"Requesting: {url}")
        response = await client.get(url, headers=headers)
        print(f"Status: {response.status_code}")
        print(f"Content Type: {response.headers.get('content-type')}")
        text = response.text
        print(f"Length: {len(text)}")
        
        if response.status_code == 200:
            soup = BeautifulSoup(text, "html.parser")
            search_results = soup.select('search-result-item')
            print(f"Found {len(search_results)} search-result-item tags")
            for item in search_results[:2]:
                title_tag = item.select_one('span[data-proto="Title"]') or item.select_one('a#link')
                title = title_tag.text.strip() if title_tag else "No title"
                
                pub_tag = item.select_one('span[data-proto="PublicationNumber"]')
                pub = pub_tag.text.strip() if pub_tag else "No pub"
                
                print(f"- {pub}: {title}")
        else:
            print("Response starts with:")
            print(text[:300])

if __name__ == "__main__":
    asyncio.run(test_normal_page())
