import asyncio
import os
import sys

sys.path.append(r"d:\S3K Technology\Apcotex\R&D Backend\R&D Product Recipe Simulator (1)\backend")

from app.db.session import AsyncSessionLocal
from app.models.research_run import ResearchRun, RunStatus
from app.models.user import User
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.services.pipeline.schemas import ExtractionResult, ExtractionStatus, PatentExtraction
from sqlalchemy import select

# Mocks
class MockSearchService:
    def build_queries(self, profile):
        return [
            {"query": "Test Polymer", "tier": "BASE_PRODUCTION", "search_field": "TITLE"},
            {"query": "Test Polymer Process", "tier": "BASE_PRODUCTION", "search_field": "TITLE"}
        ]

    def validate_query(self, query, field):
        return True, "Valid"
        
    async def search_patents_page(self, query_str, field, page, jurisdictions, date_start, date_end):
        # Return fake patents
        results = []
        for i in range(10):
            results.append({
                "position": i,
                "title": f"Method for Producing {query_str} Variant {i}",
                "patent_number": f"US2024000{page}{i}A1",
                "url": f"http://patents.google.com/patent/US2024000{page}{i}A1",
                "jurisdiction": "US",
                "publication_date": "2024-01-01",
                "snippet": "Fake snippet"
            })
        return results, True

class MockFetcherService:
    async def fetch_patent(self, url):
        from app.services.pipeline.schemas import ParsedPatent, StructuralEvidence
        return ParsedPatent(
            url=url,
            abstract="Fake abstract " * 20,  # ~100 chars -> 25 tokens
            detailed_description="Fake description " * 1000, # ~15000 chars -> 3750 tokens
            claims="Fake claims",
            examples="Fake examples",
            structural_evidence=StructuralEvidence(example_count=5)
        )

class MockExtractorService:
    async def prepare_extraction(self, parsed_patent, patent_number, title, jurisdiction, source_url, skip_llm, search_profile):
        from app.services.pipeline.extractor_service import PreparedExtractionContext
        return PreparedExtractionContext(
            patent_number=patent_number,
            title=title,
            jurisdiction=jurisdiction,
            url=source_url,
            llm_required=False,
            input_tokens=1000,
            context_str="Mock context",
            initial_json=PatentExtraction(),
            det_result=PatentExtraction(),
            raw_chars=10000,
            targeted_chars=4000
        )
        
    async def execute_extraction(self, prep_context):
        print(f"Mock Executing Extraction {prep_context.patent_number}")
        res = ExtractionResult(
            status=ExtractionStatus.FULL,
            patent_number=prep_context.patent_number,
            extraction=PatentExtraction()
        )
        return res

async def main():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        
        if not user:
            print("No user found")
            return
            
        run = ResearchRun(
            compound_name="Test Polymer",
            competitors=[],
            selected_sources=["google_patents"],
            jurisdictions=["US"],
            status=RunStatus.PENDING,
            created_by=user.id,
            report_version=1
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        
        print(f"Starting Test Run {run.id}")
        
    orchestrator = PipelineOrchestrator(run.id)
    
    # Inject mocks
    orchestrator.search_service = MockSearchService()
    orchestrator.fetcher_service = MockFetcherService()
    orchestrator.extractor_service = MockExtractorService()
    
    await orchestrator.execute()
    
    async with AsyncSessionLocal() as session:
        r = await session.get(ResearchRun, run.id)
        print(f"Run finished with status: {r.status}")

if __name__ == "__main__":
    asyncio.run(main())
