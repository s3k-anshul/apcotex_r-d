"""
Website discovery service for generating site-restricted search queries.
"""
from typing import List, Tuple
from urllib.parse import urlparse
from app.services.pipeline.schemas import CompoundSearchProfile

class WebsiteService:
    """
    Generates website-specific search queries using site-restricted search.
    
    Uses site:domain syntax to search within specific websites.
    """
    
    def __init__(self):
        pass
    
    def extract_domain(self, url: str) -> str:
        """
        Extract domain from URL.
        
        Args:
            url: Full URL or plain domain
        
        Returns:
            Domain name (e.g., example.com)
        """
        try:
            parsed = urlparse(url)
            if parsed.netloc:
                return parsed.netloc
            # If no netloc, the input might be a plain domain
            return url
        except Exception:
            return url
    
    def generate_website_queries(
        self, 
        website_url: str, 
        profile: CompoundSearchProfile
    ) -> Tuple[str, List[str]]:
        """
        Generate site-restricted search queries for a website.
        
        Args:
            website_url: URL of the website to search
            profile: Compound search profile with compound intelligence
        
        Returns:
            Tuple of (domain, list of query strings)
        """
        domain = self.extract_domain(website_url)
        queries = []
        
        # Get compound terms
        compound_terms = [profile.compound_name]
        if profile.synonyms:
            compound_terms.extend(profile.synonyms)
        if profile.abbreviations:
            compound_terms.extend(profile.abbreviations)
        
        # Production terminology
        production_terms = [
            "polymerization",
            "production",
            "preparation",
            "synthesis",
            "manufacturing"
        ]
        
        # Generate base compound queries
        for compound_term in compound_terms[:5]:
            queries.append(f'site:{domain} "{compound_term}"')
        
        # Generate production-focused queries
        for compound_term in compound_terms[:3]:
            for prod_term in production_terms[:3]:
                queries.append(f'site:{domain} {compound_term} {prod_term}')
        
        # Generate patent-specific queries
        for compound_term in compound_terms[:3]:
            queries.append(f'site:{domain} patent {compound_term}')
        
        # Generate constraint-specific queries if constraints exist
        if profile.important_constraints:
            for constraint in profile.important_constraints[:2]:
                for compound_term in compound_terms[:2]:
                    queries.append(f'site:{domain} "{compound_term}" {constraint}')
        
        return domain, queries
