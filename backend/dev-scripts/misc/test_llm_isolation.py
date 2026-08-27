import sys
import os
import asyncio

# Ensure app is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.llm.llm_client import DynamicLLMClient
from app.services.pipeline.schemas import CompoundSearchProfile

async def test_llm():
    print("--- PHASE 3: TEST LLM IN ISOLATION ---")
    
    # 1. Print Env Vars
    print("\n[DIAGNOSTICS] Environment Variables")
    from app.core.config import settings
    print(f"PRIMARY_LLM: {settings.PRIMARY_LLM}")
    print(f"FALLBACK_LLM: {settings.FALLBACK_LLM}")
    print(f"ENABLE_FALLBACK: {settings.ENABLE_FALLBACK}")
    print(f"GEMINI_API_KEY Configured: {'YES' if settings.GEMINI_API_KEY else 'NO'}")
    print(f"OPENAI_API_KEY Configured: {'YES' if settings.OPENAI_API_KEY else 'NO'}")
    print(f"GROQ_API_KEY Configured: {'YES' if settings.GROQ_API_KEY else 'NO'}")

    # 2. Test LLMClient Provider Selection
    client = DynamicLLMClient()
    print("\n[DIAGNOSTICS] Fetching Provider")
    try:
        provider_id, provider = await client._get_available_provider()
        print(f"SELECTED PROVIDER: {provider_id}")
    except Exception as e:
        print(f"ERROR Fetching Provider: {e}")
        return

    # 3. Test Structured Request (CompoundSearchProfile)
    print("\n[DIAGNOSTICS] Testing Structured Request")
    compound_name = "Low Acrylonitrile NBR"
    prompt = f"Analyze the chemical compound: {compound_name}"
    system_prompt = "You are a patent research assistant. Return the requested JSON schema."
    
    try:
        result, raw = await client.generate_structured(
            prompt=prompt,
            system_prompt=system_prompt,
            schema=CompoundSearchProfile
        )
        print(f"SUCCESS! Result: {result}")
        print("Schema validation passed.")
    except Exception as e:
        print(f"FAILED Structured Generation: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_llm())
