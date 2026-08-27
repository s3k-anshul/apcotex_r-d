"""
app/services/pipeline/cache_service.py

Simple file-based JSON cache to skip expensive parsing and LLM operations
for patents that have already been fully processed.
"""
import json
import logging
import os
import hashlib
from typing import Optional

from app.services.pipeline.schemas import PatentExtraction, ParsedPatent

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".cache")
PATENTS_DIR = os.path.join(CACHE_DIR, "patents")
SEARCH_DIR = os.path.join(CACHE_DIR, "search")
META_DIR = os.path.join(CACHE_DIR, "metadata")
HISTORY_DIR = os.path.join(CACHE_DIR, "history")
PROFILE_DIR = os.path.join(CACHE_DIR, "profiles")

class CacheService:
    def __init__(self):
        os.makedirs(PATENTS_DIR, exist_ok=True)
        os.makedirs(SEARCH_DIR, exist_ok=True)
        os.makedirs(META_DIR, exist_ok=True)
        os.makedirs(HISTORY_DIR, exist_ok=True)
        os.makedirs(PROFILE_DIR, exist_ok=True)

    def _get_cache_path(self, url: str) -> str:
        """Generate a safe, unique filename for the URL (Extraction Cache)."""
        hash_val = hashlib.md5(url.encode("utf-8")).hexdigest()
        return os.path.join(PATENTS_DIR, f"{hash_val}.json")

    def get_cached_extraction(self, url: str, force_fresh: bool = True) -> Optional[PatentExtraction]:
        """Load from cache if it exists, disabled by default for fresh extractions."""
        if force_fresh:
            logger.info("LLM Extraction cache bypassed (force_fresh=True). Executing fresh extraction.")
            return None
            
        path = self._get_cache_path(url)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info("Cache hit for URL: %s", url)
                    return PatentExtraction(**data)
            except Exception as e:
                logger.error("Failed to read cache for %s: %s", url, e)
        return None

    def save_extraction(self, url: str, extraction: PatentExtraction):
        """Save a validated extraction to cache."""
        path = self._get_cache_path(url)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(extraction.model_dump(), f, indent=2)
                logger.info("Saved extraction to cache for URL: %s", url)
        except Exception as e:
            logger.error("Failed to save cache for %s: %s", url, e)

    # ── Compound Profile Cache ──
    def _get_profile_key(self, compound: str) -> str:
        key_str = compound.lower().strip()
        return hashlib.md5(key_str.encode("utf-8")).hexdigest()

    def get_compound_profile(self, compound: str) -> Optional[object]: # Returns CompoundSearchProfile
        logger.info("\nCompound Profile Cache\nStatus: BYPASSED\nReason:\nResearch-Level Cache Disabled\n")
        return None

    def save_compound_profile(self, compound: str, profile):
        # Disabled
        pass

    # ── Search Cache ──
    def _get_search_key(self, compound: str, jurisdiction: str, comps: list) -> str:
        key_str = f"{compound.lower()}_{jurisdiction.lower()}_{'_'.join(sorted(comps))}"
        return hashlib.md5(key_str.encode("utf-8")).hexdigest()

    def get_search_cache(self, compound: str, jurisdiction: str, comps: list) -> Optional[dict]:
        logger.info("\nSearch Cache\nStatus: BYPASSED\nReason:\nResearch-Level Cache Disabled\n")
        return None

    def save_search_cache(self, compound: str, jurisdiction: str, comps: list, patents: list):
        # Disabled
        pass

    # ── Metadata Cache ──
    def get_metadata(self, patent_number: str) -> Optional[dict]:
        return None

    def save_metadata(self, patent_number: str, data: dict):
        pass

    # ── History ──
    def get_history(self, compound: str) -> dict:
        return {"used_patents": []}

    def save_history(self, compound: str, patent_numbers: list):
        pass
