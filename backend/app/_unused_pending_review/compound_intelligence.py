"""
app/services/pipeline/compound_intelligence.py

Uses Gemini to dynamically generate a CompoundSearchProfile 
from a generic compound input (e.g. "EPDM" or "Low ACN NBR").
"""
import logging
import inspect
from app.services.llm import llm_client
from app.services.pipeline.schemas import CompoundSearchProfile, LLMCompoundSearchProfile

logger = logging.getLogger(__name__)

from app.services.prompts.patent_prompts import (
    COMPOUND_SEARCH_PROFILE_SYSTEM_PROMPT,
    COMPOUND_SEARCH_PROFILE_USER_TEMPLATE
)

class CompoundIntelligenceService:
    def __init__(self, cache_service):
        self.cache_service = cache_service

    def _derive_full_profile(self, original_input: str, llm_profile: LLMCompoundSearchProfile) -> CompoundSearchProfile:
        """Maps the compact LLM profile to the full deterministic pipeline profile safely."""
        profile = CompoundSearchProfile()
        
        # Direct string mappings
        profile.original_input = str(original_input) if original_input else ""
        profile.compound_name = str(llm_profile.target_material) if getattr(llm_profile, 'target_material', None) else ""
        profile.target_material = str(llm_profile.target_material) if getattr(llm_profile, 'target_material', None) else ""
        profile.normalized_material = str(llm_profile.normalized_material) if getattr(llm_profile, 'normalized_material', None) else ""
        
        # List mappings
        profile.material_synonyms = list(llm_profile.material_synonyms) if getattr(llm_profile, 'material_synonyms', None) else []
        profile.chemical_synonyms = list(llm_profile.chemical_synonyms) if getattr(llm_profile, 'chemical_synonyms', None) else []
        profile.requested_attributes = list(llm_profile.requested_attributes) if getattr(llm_profile, 'requested_attributes', None) else []
        profile.material_variants = list(llm_profile.material_variants) if getattr(llm_profile, 'material_variants', None) else []
        profile.excluded_variants = list(llm_profile.excluded_variants) if getattr(llm_profile, 'excluded_variants', None) else []
        profile.synthesis_terms = list(llm_profile.synthesis_terms) if getattr(llm_profile, 'synthesis_terms', None) else []
        profile.process_terms = list(llm_profile.process_terms) if getattr(llm_profile, 'process_terms', None) else []
        profile.downstream_terms = list(llm_profile.downstream_terms) if getattr(llm_profile, 'downstream_terms', None) else []
        
        # Object transformations
        if getattr(llm_profile, 'search_queries', None):
            profile.search_queries = [str(q) for q in llm_profile.search_queries if q]
        else:
            profile.search_queries = []
            
        return profile

    async def generate_profile(self, compound_input: str) -> CompoundSearchProfile:
        # Check cache first
        cached_profile = self.cache_service.get_compound_profile(compound_input)
        if cached_profile:
            logger.info(f"SEARCH PROFILE REUSED for '{compound_input}'")
            return cached_profile
            
        logger.info(f"SEARCH PROFILE GENERATED for '{compound_input}'")
        
        prompt = COMPOUND_SEARCH_PROFILE_USER_TEMPLATE.format(compound_input=compound_input)
        
        # Estimate input tokens
        sys_tokens = len(COMPOUND_SEARCH_PROFILE_SYSTEM_PROMPT) // 4
        user_tokens = len(prompt) // 4
        
        # Get schema string for estimation
        import json
        schema_dict = LLMCompoundSearchProfile.model_json_schema()
        schema_tokens = len(json.dumps(schema_dict)) // 4
        
        estimated_input = sys_tokens + user_tokens + schema_tokens
        
        logger.debug(f"System prompt tokens: {sys_tokens}")
        logger.debug(f"User input tokens: {user_tokens}")
        logger.debug(f"Structured schema tokens: {schema_tokens}")
        logger.debug(f"Estimated total input: {estimated_input}")
        
        result, provider, usage = await llm_client.generate_structured(
            prompt=prompt,
            system_prompt=COMPOUND_SEARCH_PROFILE_SYSTEM_PROMPT,
            schema=LLMCompoundSearchProfile,
            temperature=0.1
        )
        
        if not result:
            logger.error("LLM Profile generation failed.")
            raise Exception(f"Failed to generate CompoundSearchProfile for {compound_input}")
            
        actual_input = usage.get('input_tokens', 'N/A')
        actual_output = usage.get('output_tokens', 'N/A')
        actual_total = usage.get('input_tokens', 0) + usage.get('output_tokens', 0)
            
        # Derive the full internal profile
        try:
            full_profile = self._derive_full_profile(compound_input, result)
            full_profile.llm_usage = usage
        except Exception as e:
            logger.error(f"Internal Profile mapping failed: {str(e)}")
            raise
        
        logger.info("=" * 60)
        logger.info("QUERY EXPANSION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Target: {compound_input}")
        logger.info(f"Profile Validation: PASS")
        logger.info(f"LLM Calls: 1")
        logger.info(f"Total Tokens: {actual_total} (In: {actual_input}, Out: {actual_output})")
        logger.info("=" * 60)
        
        # Save to cache
        self.cache_service.save_compound_profile(compound_input, full_profile)
        
        return full_profile
