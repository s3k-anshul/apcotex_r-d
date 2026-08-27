import asyncio
import logging
from app.services.llm.provider_registry import instantiate_provider, get_provider_status
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    print(f"Primary LLM config: {settings.PRIMARY_LLM}")
    print(f"Gemini Status: {get_provider_status('gemini')}")
    print(f"OpenAI Status: {get_provider_status('openai')}")
    print(f"Groq Status: {get_provider_status('groq')}")
    
    print("\nInstantiating Gemini...")
    try:
        gemini = instantiate_provider('gemini')
        print("Gemini instantiated successfully.")
    except Exception as e:
        print(f"Gemini failed: {e}")
        
    print("\nInstantiating OpenAI...")
    try:
        openai = instantiate_provider('openai')
        print("OpenAI instantiated successfully.")
    except Exception as e:
        print(f"OpenAI failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
