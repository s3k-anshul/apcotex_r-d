import asyncio
from app.services.llm.llm_client import llm_client
from app.services.pipeline.schemas import CompoundSearchProfile

async def test_minimal_structured():
    print("Testing minimal structured request...")
    prompt = "Low Acrylonitrile NBR"
    system_prompt = "Generate a CompoundSearchProfile for the given compound."
    
    try:
        result, provider_id = await llm_client.generate_structured(prompt, system_prompt, CompoundSearchProfile)
        print(f"Success with {provider_id}!")
        print(result.model_dump_json(indent=2))
    except Exception as e:
        print(f"Failed: {type(e).__name__} - {e}")
        
if __name__ == "__main__":
    asyncio.run(test_minimal_structured())
