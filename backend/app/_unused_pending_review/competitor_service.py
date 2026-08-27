"""
Competitor discovery service for generating competitor-specific patent queries.
"""
from typing import List
from app.services.pipeline.schemas import SearchQuery, SearchField, SearchPriority, SearchCategory
from app.services.pipeline.schemas import CompoundSearchProfile

class CompetitorService:
    """
    Generates competitor-specific patent search queries.
    
    Combines competitor names with compound terminology and production intent.
    """
    
    def __init__(self):
        pass
    
    def generate_competitor_queries(
        self, 
        competitor_name: str, 
        profile: CompoundSearchProfile
    ) -> List[SearchQuery]:
        """
        Generate competitor-specific search queries.
        
        Combines competitor name with:
        - Base compound name
        - Synonyms
        - Abbreviations
        - Production terminology
        
        Args:
            competitor_name: Name of the competitor company
            profile: Compound search profile with compound intelligence
        
        Returns:
            List of SearchQuery objects for competitor discovery
        """
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
            "manufacturing",
            "method for producing",
            "process for producing",
            "method for preparing",
            "process for preparing"
        ]
        
        # Generate base competitor queries (competitor + compound)
        for compound_term in compound_terms[:5]:  # Limit to avoid too many queries
            # Simple: "Zeon Nitrile Rubber"
            queries.append(SearchQuery(
                query=f"{competitor_name} {compound_term}",
                field=SearchField.TITLE,
                category=SearchCategory.EXACT,
                priority=SearchPriority.PRIMARY
            ))
        
        # Generate production-focused queries (competitor + compound + production)
        for compound_term in compound_terms[:3]:  # Limit to most important terms
            for prod_term in production_terms[:4]:  # Limit to key production terms
                queries.append(SearchQuery(
                    query=f"{competitor_name} {compound_term} {prod_term}",
                    field=SearchField.TITLE,
                    category=SearchCategory.POLYMERIZATION,
                    priority=SearchPriority.PRIMARY
                ))
        
        # Generate constraint-specific queries if constraints exist
        if profile.important_constraints:
            for constraint in profile.important_constraints[:2]:  # Limit constraints
                for compound_term in compound_terms[:2]:
                    queries.append(SearchQuery(
                        query=f"{competitor_name} {compound_term} {constraint}",
                        field=SearchField.TITLE,
                        category=SearchCategory.CONSTRAINT,
                        priority=SearchPriority.SECONDARY
                    ))
        
        return queries
    
    def matches_competitor(
        self, 
        patent_data: dict, 
        competitor_name: str
    ) -> bool:
        """
        Check if a patent matches a competitor based on assignee/applicant.
        
        Uses structured metadata from Serper when available.
        
        Args:
            patent_data: Patent metadata from Serper
            competitor_name: Name of the competitor to match
        
        Returns:
            True if patent assignee/applicant matches competitor
        """
        # Check assignee field
        assignee = patent_data.get("assignee", "")
        if assignee and competitor_name.lower() in assignee.lower():
            return True
        
        # Check applicant field
        applicant = patent_data.get("applicant", "")
        if applicant and competitor_name.lower() in applicant.lower():
            return True
        
        # Check organization field (some sources use this)
        organization = patent_data.get("organization", "")
        if organization and competitor_name.lower() in organization.lower():
            return True
        
        return False
