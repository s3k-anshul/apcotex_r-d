import asyncio
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline.validation_service import ValidationService
from app.services.pipeline.schemas import ParsedPatent, CompoundSearchProfile
from app.services.llm.llm_client import ProviderExhaustedException
import app.services.llm.llm_client as llm_client_module
import logging
from unittest.mock import AsyncMock

logging.basicConfig(level=logging.INFO)

async def main():
    try:
        print("Running Test 3 - Hammer Guard (Large Patent)")
        service = ValidationService()
        
        profile = CompoundSearchProfile(
            compound="Test",
            compound_name="Test Polymer",
            abbreviations=[],
            chemical_family="Test Family",
            alternative_industry_names=[],
            synonyms=[],
            major_monomers=[],
            typical_polymerization_routes=[],
            typical_manufacturing_keywords=[],
            typical_cpc=[],
            typical_ipc=[],
            important_constraints=[],
            related_chemistry=[],
            competing_chemistry=[],
            application_keywords=[],
            manufacturing_keywords=[]
        )
        
        # Create a large patent that will be split into at least 3 chunks
        # Chunk size is 16,000 chars. So 50,000 chars will be 4 chunks.
        large_content = "This is a large patent content. " * 2000
        parsed_patent = ParsedPatent(
            url="http://test.com",
            abstract="Abstract.",
            detailed_description=large_content,
            claims="Claims."
        )
        
        from app.services.llm.llm_client import llm_client
        # Monkey patch llm_client.generate_structured to fail on chunk 2
        original_generate = llm_client.generate_structured
        
        call_count = 0
        async def mock_generate_structured(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                print("MOCK: Artificially failing chunk 2")
                raise ProviderExhaustedException("Mock provider exhausted")
            return await original_generate(*args, **kwargs)
            
        llm_client.generate_structured = mock_generate_structured
        
        decision = await service.validate_patent_content(parsed_patent, "US-HAMMER-123", profile)
        print(f"\nDecision Result: {decision.decision}")
        print(f"Confidence: {decision.confidence}")
        print(f"Reason: {decision.reason}")
        print(f"Total API Calls: {call_count}")
        
        # We expect 2 calls (chunk 1 succeeds, chunk 2 fails). Chunks 3 and 4 should be aborted.
        if decision.decision == "INSUFFICIENT_EVIDENCE" and "LLM_PROVIDER_FAILURE" in decision.reason and call_count == 2:
            print("TEST 3: PASS (Hammer guard worked)")
        else:
            print("TEST 3: FAIL (Hammer guard failed or returned wrong decision)")
            
    except Exception as e:
        print(f"TEST 3: FAIL (Exception {e})")

if __name__ == "__main__":
    asyncio.run(main())
