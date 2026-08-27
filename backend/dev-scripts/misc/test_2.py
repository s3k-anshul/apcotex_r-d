import asyncio
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.services.pipeline.validation_service import ValidationService
from app.services.pipeline.schemas import ParsedPatent, CompoundSearchProfile
from app.db.session import AsyncSessionLocal
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)

async def main():
    try:
        print("Running Test 2 - One Patent, One Chunk")
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
        
        parsed_patent = ParsedPatent(
            url="http://test.com",
            abstract="This is a test patent about a polymer with 10% acrylonitrile. It has excellent resistance.",
            detailed_description="Polymerization occurs at 50C using an initiator.",
            claims="A polymer composition comprising acrylonitrile."
        )
        
        decision = await service.validate_patent_content(parsed_patent, "US-TEST-123", profile)
        print(f"\nDecision Result: {decision.decision}")
        print(f"Confidence: {decision.confidence}")
        print(f"Reason: {decision.reason}")
        
        if decision.decision in ["KEEP", "REJECT", "INSUFFICIENT_EVIDENCE"]:
            print("TEST 2: PASS (Valid decision format)")
        else:
            print("TEST 2: FAIL (Invalid decision format)")
            
    except Exception as e:
        print(f"TEST 2: FAIL (Exception {e})")

if __name__ == "__main__":
    asyncio.run(main())
