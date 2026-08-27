"""
Test data preservation through extraction pipeline without external API calls.
Verifies that extracted parameters are preserved through the pipeline.
"""
import asyncio
from app.services.pipeline.schemas import ParsedPatent, PatentExtraction, ExtractedParameterSchema
from app.services.pipeline.deterministic_extractor import DeterministicExtractor
from app.services.pipeline.extractor_service import ExtractorService
from app.services.pipeline.report_evidence_service import ReportEvidenceService

async def test_data_preservation():
    print("=" * 60)
    print("TEST: Data Preservation Through Pipeline")
    print("=" * 60)
    
    # Create a mock parsed patent with substantial content
    parsed = ParsedPatent(
        abstract="Test abstract for polymerization process.",
        detailed_description="""
        Example 1
        100 parts of butadiene, 12 parts of acrylonitrile, 2 parts of potassium persulfate,
        0.5 parts of emulsifier, 200 parts of water were charged into a reactor.
        The polymerization was carried out at 50°C for 8 hours.
        Conversion reached 80%.
        
        Example 2
        90 parts of butadiene, 15 parts of acrylonitrile, 3 parts of initiator,
        1 part of surfactant, 250 parts of water were used.
        Temperature was 55°C, time was 10 hours.
        Yield was 85%.
        """,
        claims="Claim 1: A polymerization process. Claim 2: The process of claim 1 wherein..."
    )
    
    # Add structural evidence
    from app.services.pipeline.schemas import StructuralEvidence
    parsed.structural_evidence = StructuralEvidence()
    parsed.structural_evidence.example_count = 2
    parsed.structural_evidence.initiator_count = 2
    parsed.structural_evidence.temperature_count = 2
    
    print(f"\n1. Parsed Patent:")
    print(f"   Abstract length: {len(parsed.abstract)}")
    print(f"   Description length: {len(parsed.detailed_description)}")
    print(f"   Examples detected: {parsed.structural_evidence.example_count}")
    
    # Test Deterministic Extraction
    print(f"\n2. Deterministic Extraction:")
    det_extractor = DeterministicExtractor()
    initial_json = PatentExtraction()
    initial_json.metadata.patent_number = "TEST123"
    initial_json.metadata.patent_title = "Test Patent"
    initial_json.metadata.jurisdiction = "US"
    
    result, detected_count = det_extractor.extract(parsed, initial_json)
    extracted_params = result.parameters
    
    print(f"   Parameters extracted: {len(extracted_params)}")
    print(f"   Candidates detected: {detected_count}")
    print(f"   Examples segmented: {len(result.examples)}")
    
    # Debug: show what was in examples
    if result.examples:
        print(f"   Example blocks:")
        for ex in result.examples:
            print(f"     - {ex.type} {ex.number}: {len(ex.raw_text)} chars")
            if ex.extracted_parameters:
                print(f"       Parameters in this block: {len(ex.extracted_parameters)}")
    
    if len(extracted_params) == 0:
        print("   ⚠ WARNING: No parameters passed validation")
        print("   This may be due to hallucination check or missing fields")
        # Try without validation for testing
        print("   Testing extraction without validation...")
        from app.services.pipeline.parser_service import ParserService
        parser = ParserService()
        blocks = parser.detect_recipe_blocks(parsed)
        print(f"   Blocks detected: {len(blocks)}")
        for block in blocks:
            print(f"     Block: {block.title} ({len(block.raw_text)} chars)")
            # Test raw extraction
            raw_params, _ = det_extractor._extract_entities(block.raw_text, block.title)
            print(f"     Raw params before validation: {len(raw_params)}")
            for p in raw_params[:3]:
                print(f"       {p.name} = {p.value} {p.unit} (in source: {p.value in p.source_sentence})")
    
    for i, param in enumerate(extracted_params[:5], 1):
        print(f"   Param {i}: {param.name} = {param.value} {param.unit}")
    
    # Test ExtractorService (without LLM)
    print(f"\n3. ExtractorService (skip LLM):")
    extractor = ExtractorService()
    extraction_result = await extractor.extract_patent(
        parsed_patent=parsed,
        patent_number="TEST123",
        title="Test Patent",
        jurisdiction="US",
        source_url="http://test.com",
        skip_llm=True
    )
    
    print(f"   Status: {extraction_result.status}")
    print(f"   Parameters preserved: {len(extraction_result.extraction.parameters)}")
    print(f"   Examples preserved: {len(extraction_result.extraction.examples)}")
    
    # Test ReportEvidenceService
    print(f"\n4. ReportEvidenceService:")
    report_service = ReportEvidenceService()
    evidence = report_service.build_compact_evidence(extraction_result.extraction)
    
    print(f"   Patent number: {evidence.patent_number}")
    print(f"   Overall parameters: {len(evidence.overall_patent_parameters)}")
    print(f"   Examples: {len(evidence.examples)}")
    
    for i, param in enumerate(evidence.overall_patent_parameters[:5], 1):
        print(f"   Param {i}: {param.name} = {param.value} {param.unit}")
    
    # Verify data preservation
    print(f"\n5. Data Preservation Verification:")
    assert len(extracted_params) > 0, "No parameters extracted by deterministic extractor"
    assert len(extraction_result.extraction.parameters) > 0, "Parameters lost after ExtractorService"
    assert len(evidence.overall_patent_parameters) > 0, "Parameters lost after ReportEvidenceService"
    
    original_count = len(extracted_params)
    final_count = len(evidence.overall_patent_parameters)
    
    print(f"   Original parameters: {original_count}")
    print(f"   Final parameters: {final_count}")
    print(f"   Preservation ratio: {final_count/original_count:.1%}")
    
    if final_count >= original_count:
        print("   ✓ SUCCESS: All parameters preserved")
    else:
        print(f"   ⚠ WARNING: {original_count - final_count} parameters lost")
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_data_preservation())
