"""
app/services/pipeline/schemas.py

Pydantic schemas used for structured LLM extraction.
These strictly define the output format expected from Gemini.
"""
from typing import Dict, List, Optional
from enum import Enum
from pydantic import BaseModel, Field

class CandidateState(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    REVIEW = "REVIEW"
    REJECTED = "REJECTED"

class RelevanceClass(str, Enum):
    DIRECT = "DIRECT"
    INDIRECT = "INDIRECT"
    IRRELEVANT = "IRRELEVANT"

class MetadataQualification(str, Enum):
    KEEP = "KEEP"
    REVIEW = "REVIEW"
    REJECT = "REJECT"

class ExtractionStatus(str, Enum):
    FULL = "FULL"                          # Both deterministic + LLM succeeded
    PARTIAL = "PARTIAL"                    # Only deterministic; LLM skipped or found nothing extra
    FAILED = "FAILED"                      # Complete failure (fetch/parse error)
    LLM_FAILED = "LLM_FAILED"             # LLM was attempted but failed; deterministic preserved
    NO_USABLE_EVIDENCE = "NO_USABLE_EVIDENCE"  # Neither deterministic nor LLM found any parameters

from enum import Enum

class SearchField(str, Enum):
    TITLE = "TITLE"
    TAC = "TAC"

class SearchCategory(str, Enum):
    MANUFACTURING = "MANUFACTURING"
    PREPARATION = "PREPARATION"
    POLYMERIZATION = "POLYMERIZATION"
    PROCESS = "PROCESS"
    CHEMISTRY = "CHEMISTRY"
    EXACT = "EXACT"
    CONSTRAINT = "CONSTRAINT"
    SYNTHESIS = "SYNTHESIS"
    SYNONYM = "SYNONYM"
    BROAD = "BROAD"

class SearchPriority(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    FALLBACK = "FALLBACK"

class TargetAttribute(BaseModel):
    name: str
    condition: str
    terms: list[str]

class SearchQuery(BaseModel):
    query: str
    field: SearchField = SearchField.TITLE
    category: SearchCategory = SearchCategory.POLYMERIZATION
    priority: SearchPriority = SearchPriority.PRIMARY

class RankedCandidate(BaseModel):
    publication_number: str = Field(description="Must perfectly match input publication number")
    score: int = Field(description="Relevance score from 0-100")
    decision: str = Field(description="Decision: 'KEEP' or 'REJECT'")
    reason: str = Field(description="Brief justification for the decision")
    title_evidence: list[str] = Field(default_factory=list, description="Key phrases from the title supporting the decision")

class RankedCandidateList(BaseModel):
    ranked_candidates: list[RankedCandidate]

class ConfidenceDimensions(BaseModel):
    compound_evidence: list[str] = Field(default_factory=list)
    matched_monomers: list[str] = Field(default_factory=list)
    matched_synonyms: list[str] = Field(default_factory=list)
    matched_chemistry_family: list[str] = Field(default_factory=list)
    manufacturing_evidence: list[str] = Field(default_factory=list)
    recipe_evidence: list[str] = Field(default_factory=list)
    negative_evidence: list[str] = Field(default_factory=list)
    competing_chemistry: list[str] = Field(default_factory=list)
    search_confidence: int = 0
    target_chemistry_score: int = 0
    synthesis_score: int = 0
    recipe_score: int = 0
    
    @property
    def has_compound_evidence(self) -> bool:
        return len(self.compound_evidence) > 0 or len(self.matched_monomers) >= 2 or len(self.matched_synonyms) > 0 or len(self.matched_chemistry_family) > 0
        
    @property
    def has_manufacturing_evidence(self) -> bool:
        return len(self.manufacturing_evidence) > 0
        
    @property
    def has_recipe_evidence(self) -> bool:
        return len(self.recipe_evidence) > 0

    @property
    def overall_confidence(self) -> int:
        score = 0
        score += len(self.compound_evidence) * 50
        score += len(self.matched_synonyms) * 30
        score += len(self.matched_monomers) * 15
        score += len(self.matched_chemistry_family) * 10
        score += len(self.manufacturing_evidence) * 10
        score += len(self.recipe_evidence) * 15
        score += self.search_confidence
        score -= len(self.negative_evidence) * 20
        score -= len(self.competing_chemistry) * 15
        return max(0, score)

class EvidenceLedger(BaseModel):
    state: CandidateState = CandidateState.LOW
    relevance: RelevanceClass = RelevanceClass.INDIRECT
    dimensions: ConfidenceDimensions = Field(default_factory=ConfidenceDimensions)
    matched_queries: list[str] = Field(default_factory=list)
    query_match_count: int = 0
    search_families: list[SearchCategory] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)
    rejection_reason: str = ""
    
    def log(self, message: str):
        self.history.append(message)

class StructuralEvidence(BaseModel):
    has_preparation_example: bool = False
    has_experimental_example: bool = False
    has_working_example: bool = False
    has_embodiment: bool = False
    has_detailed_description: bool = False
    has_claims: bool = False
    example_count: int = 0
    table_count: int = 0
    temperature_count: int = 0
    pressure_count: int = 0
    initiator_count: int = 0
    emulsifier_count: int = 0
    chain_transfer_count: int = 0
    conversion_count: int = 0
    coagulation_count: int = 0
    wt_percent_count: int = 0
    phr_count: int = 0
    numeric_density: float = 0.0
    example_density: float = 0.0

class ExtractedParameterSchema(BaseModel):
    name: str = ""
    category: str = ""
    value: str = ""
    unit: str = ""
    evidence: str = "Not disclosed"
    source_section: str = "Not disclosed"
    context: str = ""
    section: str = ""
    example_number: str = ""
    source_sentence: str = ""
    confidence: float = 0.0
    source_offset: int = 0
    extraction_method: str = "deterministic"

class SynthesisSection(BaseModel):
    section_title: str = ""
    raw_text: str = ""

class ExtractedExampleParameterSchema(BaseModel):
    name: str = ""
    value: str = ""
    unit: str = ""
    source: str = ""

class PatentExample(BaseModel):
    example_id: str = ""
    example_type: str = ""
    title: str = ""
    raw_text: str = ""
    extracted_parameters: list[ExtractedExampleParameterSchema] = Field(default_factory=list)

class ParsedPatent(BaseModel):
    """
    Schema for the deterministic output of the parser stage.
    """
    url: str = ""
    patent_number: str = Field(description="Canonical patent identifier", default="")
    title: str = Field(description="Title of the patent", default="")
    jurisdiction: str = Field(description="Jurisdiction of the patent", default="")
    publication_date: str = Field(description="Publication date of the patent", default="")
    assignee: str = Field(description="Assignee of the patent", default="")
    metadata: Dict[str, str] = Field(default_factory=dict)
    abstract: str = ""
    summary: str = ""
    detailed_description: str = ""
    examples: str = ""
    tables: List[Dict] = Field(default_factory=list)
    claims: str = ""
    structural_evidence: StructuralEvidence = Field(default_factory=StructuralEvidence)
    
    def get_llm_context(self) -> str:
        """Returns only the relevant sections for the LLM to process, optimizing token limits."""
        import re
        context = []
        if self.abstract:
            context.append(f"--- ABSTRACT ---\n{self.abstract}")
        if self.claims:
            context.append(f"--- CLAIMS ---\n{self.claims}")
        
        if self.detailed_description:
            # Smart chunking around critical keywords to reduce 19k+ token blobs
            keywords = r'(acrylonitrile|butadiene|polymerization|emulsion|initiator|emulsifier|chain transfer|conversion|temperature|monomer ratio|example)'
            paragraphs = self.detailed_description.split('\n')
            relevant_paragraphs = []
            
            # Keep first 5 paragraphs (usually summary/background)
            relevant_paragraphs.extend(paragraphs[:5])
            
            # Keep paragraphs containing keywords
            for p in paragraphs[5:]:
                if re.search(keywords, p, re.IGNORECASE) and len(p.strip()) > 20:
                    relevant_paragraphs.append(p)
                    
            chunked_desc = "\n".join(relevant_paragraphs)
            
            # Prevent extreme lengths even after chunking
            if len(chunked_desc) > 30000:
                chunked_desc = chunked_desc[:30000] + "\n[... TRUNCATED DUE TO LENGTH ...]"
                
            context.append(f"--- RELEVANT DESCRIPTION CHUNKS ---\n{chunked_desc}")
            
        if self.examples:
            # Examples are critical, do not brutally truncate in the middle
            ex_text = self.examples
            if len(ex_text) > 40000:
                ex_text = ex_text[:40000] + "\n[... TRUNCATED EXAMPLES DUE TO LENGTH ...]"
            context.append(f"--- EXAMPLES ---\n{ex_text}")
            
        if self.tables:
            # Just stringify the first few tables to avoid blowing up context
            tbls_str = str(self.tables[:5])
            context.append(f"--- TABLES ---\n{tbls_str}")
            
        return "\n\n".join(context)

class ContentValidationSchema(BaseModel):
    relevance: RelevanceClass
    confidence: int
    target_chemistry_evidence: list[str] = Field(default_factory=list)
    synthesis_evidence: list[str] = Field(default_factory=list)
    exclusion_reason: str = ""
class PatentMetadata(BaseModel):
    url: str = Field(description="The source URL of the patent (populated automatically).", default="")
    patent_number: str = Field(description="The formal patent publication number (e.g., US1234567A)", default="Not disclosed")
    patent_title: str = Field(description="Title of the patent", default="Not disclosed")
    assignee: str = Field(description="The company or assignee who owns the patent", default="Not disclosed")
    publication_year: str = Field(description="The year the patent was published", default="Not disclosed")
    jurisdiction: str = Field(description="The country or jurisdiction of the patent (e.g., US, EP, WO)", default="Not disclosed")
    legal_status: str = Field(description="The legal status of the patent (e.g. Active, Expired)", default="Unknown")
    quality: str = Field(description="The validation quality of the extraction (High, Medium, Low)", default="Not disclosed")
    extraction_score: int = Field(description="The relative score for candidate sorting", default=0)

class ExamplesData(BaseModel):
    example_tables: list[str] = Field(description="Extracted tables related to examples", default_factory=list)
    reaction_procedure: str = Field(description="The specific steps and procedure for the reaction", default="Not disclosed")
    experimental_notes: str = Field(description="Any other important synthesis notes or anomalies", default="Not disclosed")

class PatentExtraction(BaseModel):
    """
    Final Schema for extracting structured polymerization data from a single patent.
    """
    metadata: PatentMetadata = Field(default_factory=PatentMetadata)
    experimental_notes: ExamplesData = Field(default_factory=ExamplesData)
    claims: list[str] = Field(description="Independent claims of the patent", default_factory=list)
    parameters: list[ExtractedParameterSchema] = Field(default_factory=list)
    examples: list[PatentExample] = Field(default_factory=list)
    synthesis_sections: list[SynthesisSection] = Field(default_factory=list)
    raw_text: str = Field(default="")

class ExtractionResult(BaseModel):
    status: ExtractionStatus
    patent_number: str
    extraction: PatentExtraction

class GeneratedQuery(BaseModel):
    query: str = Field(description="The actual Boolean query string to execute (e.g. '(hydrogenated AND (NBR OR HNBR))')")
    required_concepts: list[str] = Field(description="List of concepts that MUST be present in the document")
    alternative_concepts: list[str] = Field(description="List of alternative synonyms used in OR groups")
    intent: str = Field(description="The scientific intent of this query (e.g. 'direct synthesis', 'precursor synthesis')")
    scope: str = Field(description="Must be 'title' or 'full_text'")

class LLMCompoundSearchProfile(BaseModel):
    """
    Compact, LLM-facing schema for generating query expansion profiles.
    """
    original_input: str = Field(description="The exact user input")
    synthesis_intent: bool = Field(default=False, description="True if the user's research objective requires synthesizing, preparing, or manufacturing the target material.")
    base_material: list[str] = Field(default_factory=list, description="The canonical chemical base and its synonyms/aliases")
    important_negative_concepts: list[str] = Field(default_factory=list, description="Concepts that are explicitly antithetical to the target (e.g. chemical variants to exclude).")
    target_modifications: list[str] = Field(default_factory=list, description="Target variants or modifications requested")
    target_attributes: list[str] = Field(default_factory=list, description="Constraints/attributes requested")
    synthesis_transformations: list[str] = Field(default_factory=list, description="Chemical transformations (e.g. hydrogenation)")
    precursor_relationships: list[str] = Field(default_factory=list, description="Precursor materials relevant to synthesis")
    relevant_process_concepts: list[str] = Field(default_factory=list, description="Process-specific parameters or conditions")
    downstream_terms: list[str] = Field(default_factory=list, description="Terms indicating downstream applications to reject (e.g. 'hose', 'tire')")
    excluded_variants: list[str] = Field(default_factory=list, description="Variants that should be explicitly EXCLUDED")
    attribute_dimension_ranges: list[str] = Field(
        default_factory=list,
        description=(
            "For TYPE_B (attribute/range) targets: list of strings describing the typical/reference "
            "numeric range for each target attribute dimension, e.g. "
            "'acrylonitrile content: 15-25 wt% typical for standard grade; low-ACN grade: <20 wt%'. "
            "Leave empty for TYPE_A transformation targets."
        )
    )
    search_queries: list[GeneratedQuery] = Field(default_factory=list, description="Exactly 15 dynamically generated Boolean search queries.")

class CompoundSearchProfile(BaseModel):
    """
    Internal pipeline schema containing deterministic sets derived from the LLM output.
    """
    original_input: str = ""
    base_material: list[str] = Field(default_factory=list)
    target_modifications: list[str] = Field(default_factory=list)
    target_attributes: list[str] = Field(default_factory=list)
    synthesis_transformations: list[str] = Field(default_factory=list)
    precursor_relationships: list[str] = Field(default_factory=list)
    relevant_process_concepts: list[str] = Field(default_factory=list)
    downstream_terms: list[str] = Field(default_factory=list)
    excluded_variants: list[str] = Field(default_factory=list)
    attribute_dimension_ranges: list[str] = Field(default_factory=list)
    search_queries: list[GeneratedQuery] = Field(default_factory=list)
    llm_usage: dict = Field(default_factory=dict)

class ReportExampleEvidence(BaseModel):
    example_id: str
    raw_text: str = ""
    relevance_classification: str = Field(default="UNKNOWN", description="POLYMERIZATION_RELEVANT, POLYMER_CHARACTERIZATION_RELEVANT, COMPOUNDING_ONLY, IRRELEVANT")
    extracted_parameters: list[ExtractedParameterSchema] = Field(default_factory=list)
    
class SynthesisSectionEvidence(BaseModel):
    section_title: str
    raw_text: str
    
class ReportPatentEvidence(BaseModel):
    patent_number: str
    title: str
    jurisdiction: str
    assignee: str
    publication_year: str
    url: str
    discovery_source: str = Field(default="NORMAL", description="NORMAL, COMPETITOR, or WEBSITE")
    competitor_name: str | None = Field(default=None, description="Competitor name if discovery_source is COMPETITOR")
    overall_patent_parameters: list[ExtractedParameterSchema] = Field(default_factory=list)
    examples: list[ReportExampleEvidence] = Field(default_factory=list)
    synthesis_sections: list[SynthesisSectionEvidence] = Field(default_factory=list)
    technical_findings: list[str] = Field(default_factory=list)
    limitations_or_missing_data: list[str] = Field(default_factory=list)
    # Source text: abstract + deterministically-extracted relevant passages.
    # Used as the primary evidence carrier when structured parameter extraction yields 0 params.
    source_text: str = Field(default="", description="Relevant source passages (abstract, synthesis sections, examples text)")
    relevance_tier: str = Field(default="", description="Relevance tier from title screening: STRONG, MEDIUM, or WEAK")
    relevance_score: float = Field(default=0.0, description="Numeric relevance score from title screening")


class ReportPatentDetails(BaseModel):
    patent_number: str = Field(description="The formal patent publication number (e.g., US1234567A)")
    patent_title: str = Field(description="Title of the patent")
    assignee: str | None = Field(default=None, description="The company or assignee who owns the patent")
    jurisdiction: str | None = Field(default=None, description="The country or jurisdiction of the patent (e.g., US, EP, WO)")
    publication_year: str | None = Field(default=None, description="The year the patent was published")
    priority_date: str | None = Field(default=None, description="The priority date of the patent, if available")
    legal_status: str | None = Field(default=None, description="The legal status (Active, Expired, etc.)")
    polymer_type: str | None = Field(default=None, description="The type of polymer synthesized")
    relevance_to_target: str = Field(default="Not disclosed", description="Why this patent is relevant to the target compound")
    relevance_tier: str = Field(default="PRIMARY", description="Classification tier: PRIMARY or SECONDARY")

class ReportPatentMethodology(BaseModel):
    dynamic_parameters: list[str] = Field(description="Dynamically extracted reaction parameters formatted as 'Key: Value'")

class ReportPatent(BaseModel):
    patent_details: ReportPatentDetails
    polymerization_method: ReportPatentMethodology
    experimental_evidence: list[str] = Field(description="List of logical bullet points synthesizing the examples")
    technical_relevance: str = Field(description="Explanation of WHY the patent is relevant to the requested polymerization research")

class PatentResearchReport(BaseModel):
    title: str | None = Field(default=None, description="Title of the report")
    abstract: str | None = Field(default=None, description="Abstract of the report")
    methodology_patents: list[ReportPatent] = Field(description="List of extracted patents (PRIMARY tier)", default_factory=list)
    cross_patent_comparison: list[str] = Field(description="Cross-patent comparison and synthesis trends (only when >= 2 PRIMARY patents)", default_factory=list)
    conclusion: str | None = Field(default=None, description="Conclusion of the report")
    references: list[str] = Field(description="References from validated evidence only", default_factory=list)

class LLMPatentAnalysis(BaseModel):
    """
    Per-patent synthesis analysis produced by the LLM from the raw evidence.
    Keyed by patent_number so report_service.py can look it up when building
    ReportPatentMethodology. Dynamic — no fixed field list per compound.
    """
    patent_number: str = Field(description="Patent number exactly as it appears in the evidence (e.g. EP2473281B1)")
    synthesis_method: str = Field(
        default="",
        description="1-3 sentence description of the polymerization/synthesis method disclosed in this patent"
    )
    disclosed_parameters: list[str] = Field(
        default_factory=list,
        description=(
            "List of experimentally disclosed parameters from this patent, formatted as "
            "'Parameter Name: value unit — source context'. "
            "Only include values explicitly stated in the evidence. "
            "Examples: 'Hydrogenation pressure: 50 bar — Example 1', "
            "'Catalyst loading: 0.1 mol% — Example 2', "
            "'Reaction temperature: 80°C — Example 1'. "
            "Do NOT invent values. If nothing is explicitly disclosed, return an empty list."
        )
    )
    example_highlights: list[str] = Field(
        default_factory=list,
        description=(
            "Key findings from specific examples in this patent. "
            "Format: 'Example N: brief description of what was demonstrated'. "
            "Maximum 5 entries."
        )
    )
    technical_relevance: str = Field(
        default="",
        description="1-2 sentence explanation of why this patent is relevant to the target compound synthesis"
    )


class LLMPatentResearchReport(BaseModel):
    """
    Schema for the LLM to output the complete report.
    per_patent_analysis: one entry per patent in the manifest, providing
    synthesis method + disclosed parameters + example highlights.
    """
    title: str | None = Field(default=None, description="Title of the report")
    abstract: str | None = Field(default=None, description="Abstract of the report")
    per_patent_analysis: list[LLMPatentAnalysis] = Field(
        default_factory=list,
        description=(
            "Per-patent analysis — REQUIRED. One entry for every patent in the REQUIRED PATENT MANIFEST. "
            "Each entry must identify the synthesis method and all explicitly disclosed parameters "
            "from that patent's evidence. Do not skip any patent from the manifest."
        )
    )
    cross_patent_comparison: list[str] = Field(description="Cross-patent comparison and synthesis trends (only when >= 2 PRIMARY patents)", default_factory=list)
    conclusion: str | None = Field(default=None, description="Conclusion of the report")
    references: list[str] = Field(description="References from validated evidence only", default_factory=list)

class PatentBatchFindings(BaseModel):
    patent_number: str
    findings: str

class BatchAnalysisResult(BaseModel):
    patent_findings: list[PatentBatchFindings] = Field(default_factory=list)

class PatentRank(BaseModel):
    """
    Schema for an individual patent ranking.
    """
    patent: str = Field(description="The patent number (e.g., US6753382).")
    score: int = Field(description="The relevance score from 0 to 100.")
    reason: str = Field(description="Brief reason for the score, specifically relating to synthesis/polymerization detail.")

class PatentRankList(BaseModel):
    """
    Schema for a list of ranked patents.
    """
    rankings: list[PatentRank] = Field(description="A sorted list of ranked patents.")

class RankingStatus(str, Enum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"

class PatentRankResult(BaseModel):
    """
    Wrapper for the ranking result to cleanly differentiate business logic from infrastructure failures.
    """
    status: RankingStatus
    rankings: list[PatentRank] = Field(default_factory=list)
    provider: str
    error: Optional[str] = None

class AIStrategyResult(BaseModel):
    """
    Schema for the output of the AI Search Planning phase.
    """
    target_material: str = Field(description="The primary target material identified from the input (e.g. 'Nitrile Butadiene Rubber').")
    material_synonyms: list[str] = Field(default_factory=list, description="Common material synonyms and abbreviations (e.g. 'NBR').")
    target_value: str = Field(description="The numeric or qualitative value of the target property (e.g., 'low', 'high', '30%'). Leave empty if not applicable.", default="")
    target_direction: str = Field(description="The direction of the target property (e.g., 'decrease', 'increase', 'low'). Leave empty if not applicable.", default="")
    synthesis_intent: list[str] = Field(default_factory=list, description="Primary intent keywords for creating the material (e.g., 'polymerization', 'copolymerization').")
    chemical_entities: list[str] = Field(default_factory=list, description="Constituent monomers or key chemical components.")
    excluded_variants: list[str] = Field(default_factory=list, description="Variants that should be explicitly EXCLUDED.")
    synthesis_terms: list[str] = Field(default_factory=list, description="Terms related to polymerization/synthesis of the target.")
    downstream_terms: list[str] = Field(default_factory=list, description="Terms indicating downstream application.")
    requested_attributes: list[str] = Field(default_factory=list, description="Constraints/attributes explicitly requested.")
    search_queries: list[str] = Field(
        description="A list of exactly 15 simple, semantically diverse search queries targeting polymer synthesis methods."
    )
    rationale: str = Field(
        description="Brief explanation of the search strategy."
    )

class TitleTriageClassification(str, Enum):
    DIRECT_SYNTHESIS = "DIRECT_SYNTHESIS"
    TARGET_TRANSFORMATION = "TARGET_TRANSFORMATION"
    POLYMER_STRUCTURE = "POLYMER_STRUCTURE"
    PRECURSOR_OR_INTERMEDIATE = "PRECURSOR_OR_INTERMEDIATE"
    BASE_MATERIAL_ONLY = "BASE_MATERIAL_ONLY"
    DOWNSTREAM_APPLICATION = "DOWNSTREAM_APPLICATION"
    UNRELATED = "UNRELATED"
    AMBIGUOUS = "AMBIGUOUS"

class TitleTriageCandidate(BaseModel):
    patent_number: str = Field(description="Must perfectly match input patent number")
    classification: TitleTriageClassification = Field(description="Classification of the patent")
    priority: str = Field(description="Priority derived from classification: HIGH, MEDIUM_HIGH, MEDIUM, or LOW")
    relevance: str = Field(description="Relevance confidence: HIGH, MEDIUM, or LOW")
    material_match: bool = Field(description="True if base material is the primary subject")
    target_match: bool = Field(description="True if target attribute/modification is present or plausible")
    synthesis_relevance: bool = Field(description="True if this is about synthesis/preparation/modification")
    downstream_application: bool = Field(description="True if this is merely a downstream use")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0")
    reason: str = Field(description="Brief reason for classification")

class TitleTriageResult(BaseModel):
    candidates: list[TitleTriageCandidate] = Field(default_factory=list)
