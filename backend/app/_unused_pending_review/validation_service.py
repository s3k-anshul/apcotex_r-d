"""
app/services/pipeline/validation_service.py

Validation Service — DETERMINISTIC ONLY
=========================================
Architecture: 3 LLM calls in the live pipeline path (query expansion in
search_service.py, title triage in orchestrator.py, report generation in
report_service.py). This service is NOT one of them.

All validation is deterministic:
- validate_patent_content: accepts all fetched patents (relevance already determined by title scorer)
- rank_titles: returns candidates unchanged (title scorer already ranked them)
- extract_chunk_evidence: stub, returns None

LLM chunk evidence extraction and LLM patent decision have been removed.
"""
import logging
from app.services.pipeline.schemas import ParsedPatent, CompoundSearchProfile

logger = logging.getLogger(__name__)


class ValidationService:

    async def extract_chunk_evidence(
        self, chunk_text: str, chunk_id: int, profile: CompoundSearchProfile
    ):
        """
        Stub — LLM chunk evidence extraction removed.
        All relevant evidence is gathered deterministically by DeterministicExtractor.
        """
        return None

    async def validate_patent_content(
        self,
        parsed_patent: ParsedPatent,
        patent_number: str,
        profile: CompoundSearchProfile,
    ):
        """
        Deterministic patent content validation.
        Patents that pass preliminary screening are accepted unconditionally here.
        The preliminary screening (via orchestrator _deterministic_rank) already applied the relevance gate;
        patents that pass it are suitable for evidence extraction.

        Returns a PatentValidationDecision-compatible dict for downstream compatibility.
        LLM calls = 0.
        """
        from app.services.pipeline.schemas import PatentValidationDecision
        logger.debug("[VALIDATION] %s -> ACCEPTED (deterministic, no LLM)", patent_number)
        return PatentValidationDecision(
            publication_number=patent_number,
            decision="KEEP",
            confidence=75,
            reason="Deterministic validation: patent passed title relevance screening"
        )

    async def rank_titles(
        self, candidates: list, profile: CompoundSearchProfile
    ) -> list:
        """
        Stub — LLM title ranking removed.
        Preliminary ranking already produces a deterministic relevance score in the orchestrator.
        This method returns candidates unchanged for interface compatibility.
        LLM calls = 0.
        """
        return candidates
