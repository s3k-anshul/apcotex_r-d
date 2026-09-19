"""
app/services/prompts/patent_prompts.py

Single source of truth for all LLM prompts used in the patent research workflow.
Organized by pipeline stage.
"""

# ============================================================
# PROMPT VERSION
# ============================================================
PROMPT_VERSION = "1.0"

# ============================================================
# COMPOUND SEARCH PROFILE
# ============================================================

PATENT_QUERY_EXPANSION_PROMPT = """
You are a senior polymer scientist, chemical-process researcher, and patent-search strategist specializing in polymer synthesis, copolymerization, industrial chemical processes, and patent literature.

Your task is to analyze the user's target product and generate a professional patent-search strategy focused specifically on SYNTHESIS, POLYMERIZATION, PREPARATION, and MANUFACTURING.

TARGET PRODUCT:
{compound_name}

COMPETITORS:
{competitors}

WEBSITES:
{websites}

JURISDICTIONS:
{jurisdictions}

DATE FILTER:
{publication_filter}

First internally decompose the input into a DYNAMIC TARGET SPECIFICATION:
A. BASE MATERIAL (canonical polymer/material name + synonyms/abbreviations for THIS input)
B. TARGET MODIFICATION / VARIANT / QUALIFIERS (if any)
C. TARGET PROPERTIES / ATTRIBUTES that define the requested characteristic for THIS input
   (e.g. a composition dimension, functionalization metric — derived dynamically, never from a fixed catalog)
D. SYNTHESIS TRANSFORMATION (process classes relevant to producing/modifying THIS target)
E. PRECURSOR RELATIONSHIP (precursors/intermediates relevant to THIS target, if any)
F. RELEVANT PROCESS CONCEPTS (process parameters relevant to THIS target)
G. IDENTITY EXCLUSIONS — adjacent materials/architectures often co-mentioned that are NOT
   the requested PRIMARY target (e.g. larger polymer systems that may contain a segment of the target)
H. RELATED MATERIALS — adjacent materials that may be retained as RELATED but not PRIMARY
I. RELEVANCE DEFINITION — one short paragraph: what invention subject counts as PRIMARY_TARGET
   for THIS user input based on BASE MATERIAL identity (what the patent must be ABOUT).
   Do NOT require the requested qualifier/attribute to be disclosed for PRIMARY identity.
J. EXCLUDED OR DOWNSTREAM APPLICATION CONCEPTS (end-use indicators for THIS domain — for classification only)

CRITICAL GOOGLE PATENTS BOOLEAN RULES:
1. Google Patents supports Boolean searching. Do NOT generate flat keyword lists.
2. REQUIRED CONCEPTS must be connected with AND.
3. ALTERNATIVE SYNONYMS must be connected with OR and wrapped in parentheses.
4. Distinguish TARGET TRANSFORMATION from BASE MATERIAL. DO NOT make them interchangeable.
   - BAD: (modification OR base OR variant) as a flat OR bag that matches any term alone.
   - GOOD: (modification AND (base OR synonym1 OR synonym2)) so the transformation is mandated with the material.
5. Do NOT force every query to include the requested qualifier/attribute tokens.
   Split discovery into:
   - IDENTITY/DISCOVERY queries (majority): base material + synthesis/preparation/polymerization/
     production/composition/manufacturing — WITHOUT requiring the qualifier in every query.
   - QUALIFIER/PROPERTY queries (minority, typically 3–5 of 15): base material + requested
     qualifier/attribute/content terms.
   Relevant base-material patents often omit the qualifier in search-visible fields.
6. Title-specific queries are highly precise. Use the `TI=(...)` syntax for title queries. For full-text queries, just write the boolean expression.

DISCOVERY INTENT HAS PRIORITY:
Do NOT generate separate queries around extraction fields (e.g. "initiator" alone). Emphasize synthesis and the target material for THIS compound.
Do NOT force every query to include every target property token — preserve BROAD RECALL.
Identity filtering and qualifier evaluation happen later during selection/extraction.

DO NOT USE AGGRESSIVE NEGATIVE FILTERING:
Do NOT add broad exclusions like `NOT (tire OR hose OR adhesive OR battery OR electrode)` to the generated queries. A genuine synthesis patent can mention applications of the synthesized material. Negative filtering will be handled semantically downstream. Use `important_negative_concepts` strictly for classifying chemically incompatible variants, not for discovery blocking.

Generate EXACTLY 15 DISTINCT search queries. The purpose is HIGH RECALL.
Mix them strategically across these complementary concepts:
A. Exact target-material identity searches (no qualifier required)
B. Material + synthesis/preparation searches
C. Material + polymerization searches
D. Material + production/manufacturing searches
E. Material + composition searches (identity-oriented)
F. Broader synonym identity searches
G. Qualifier/property searches (material + requested qualifier/attribute) — minority of the 15
H. Target transformation searches (when applicable)

Include a mix of 5 TITLE-FOCUSED QUERIES (using `TI=(...)`) and 10 FULL TEXT QUERIES.
Of the 15, prefer ~10–12 identity/discovery queries and ~3–5 qualifier/property queries when a qualifier exists.
Do NOT dedicate discovery queries to end-use applications (seals, hoses, gloves, tires, adhesives-as-articles).
Those downstream terms belong in downstream_terms for later classification, not in search_queries.

Return structured output matching the LLMCompoundSearchProfile schema:
- original_input: the exact user input
- synthesis_intent: boolean (true if the research objective requires synthesizing, preparing, or manufacturing the target material; false if it is merely asking for properties or applications)
- base_material: the canonical chemical base and its synonyms/aliases for THIS input
- important_negative_concepts: concepts explicitly antithetical to the target (e.g. chemical variants to exclude). DO NOT put downstream applications here.
- target_modifications: target variants or modifications / qualifiers requested
- target_attributes: human-readable labels for the target-specific properties relevant to THIS input
- synthesis_transformations: chemical transformations relevant to THIS input
- precursor_relationships: precursor materials relevant to synthesis of THIS target
- relevant_process_concepts: process-specific parameters or conditions for THIS target
- downstream_terms: words indicating applications to weigh during later selection (not discovery blocking)
- excluded_variants: chemically different materials to explicitly penalize for THIS input
- identity_exclusions: adjacent materials/systems that must NOT be treated as PRIMARY_TARGET merely because they mention the target as a segment/component
- related_materials: adjacent materials that may justify RELATED_TARGET retention
- relevance_definition: short definition of PRIMARY_TARGET based on BASE MATERIAL identity for THIS input (qualifier disclosure is NOT required for identity)
- attribute_dimension_ranges: ONLY for attribute/range targets. For each such attribute dimension,
  provide a string describing typical numeric ranges for THIS base material derived from scientific
  knowledge of the specific compound — never a fixed global dictionary. Leave empty [] for
  pure transformation targets (e.g. hydrogenation, carboxylation) with no attribute range.
- search_queries: an array of EXACTLY 15 GeneratedQuery objects. Each object MUST have:
  * query: The exact Boolean expression to send to Google Patents
  * required_concepts: List of concepts that must be present
  * alternative_concepts: List of synonyms used in the OR groups
  * intent: Brief scientific intent of this query
  * scope: "title" or "full_text"
"""

# Optional constraint blocks appended ONLY when the client supplies them.
# When both are omitted / "any", build_query_expansion_prompt() returns the
# base PATENT_QUERY_EXPANSION_PROMPT.format(...) result unchanged.

ATTRIBUTE_CONSTRAINT_INSTRUCTIONS = """
OPTIONAL USER ATTRIBUTE CONSTRAINT (ACTIVE):
The user specified this exact attribute/range constraint:
{attribute_constraint}

In ADDITION TO (not instead of) the existing 15-query diversity mix above, ensure that
at least 2–3 of the 15 GeneratedQuery objects explicitly incorporate this attribute/range
language (or clearly equivalent scientific phrasing) in their Boolean expressions and
required_concepts. Do not drop general synthesis/preparation diversity to make room —
weave the constraint into a subset of the existing mix.
"""

POLYMERIZATION_MEDIUM_AQUEOUS_INSTRUCTIONS = """
OPTIONAL POLYMERIZATION MEDIUM CONSTRAINT (ACTIVE): aqueous / emulsion
Bias query generation toward emulsion / aqueous-phase terminology where scientifically
appropriate (examples: emulsifier, surfactant, aqueous phase, latex, redox initiator,
emulsion polymerization, cold emulsion). Explicitly DEPRIORITIZE solvent / anionic
solution-polymerization-specific terms in the generated queries (examples: n-butyllithium,
THF, hexane, solution polymerization, anionic polymerization in organic solvent).
Do not change excluded_variants or downstream_terms generation rules.
"""

POLYMERIZATION_MEDIUM_SOLVENT_INSTRUCTIONS = """
OPTIONAL POLYMERIZATION MEDIUM CONSTRAINT (ACTIVE): solvent
Bias query generation toward solvent / solution / anionic polymerization terminology
where scientifically appropriate (examples: solution polymerization, n-butyllithium,
THF, hexane, anionic polymerization, living polymerization in organic solvent).
Explicitly DEPRIORITIZE emulsion / aqueous-phase-specific terms in the generated queries
(examples: emulsifier, latex, aqueous phase, cold emulsion, redox initiator in water).
Do not change excluded_variants or downstream_terms generation rules.
"""


def build_query_expansion_constraint_suffix(
    attribute_constraint: str | None = None,
    polymerization_medium: str = "any",
) -> str:
    """
    Return optional instruction text to append to the base expansion prompt.
    Empty string when no constraints are active — keeps unconstrained prompts
    byte-identical to the historical base prompt.
    """
    parts: list[str] = []
    constraint = (attribute_constraint or "").strip()
    if constraint:
        parts.append(
            ATTRIBUTE_CONSTRAINT_INSTRUCTIONS.format(attribute_constraint=constraint)
        )

    medium = (polymerization_medium or "any").strip().lower()
    if medium in ("aqueous", "emulsion"):
        parts.append(POLYMERIZATION_MEDIUM_AQUEOUS_INSTRUCTIONS)
    elif medium == "solvent":
        parts.append(POLYMERIZATION_MEDIUM_SOLVENT_INSTRUCTIONS)
    # "any" or unknown → no medium block

    if not parts:
        return ""
    return "\n" + "\n".join(parts)


def build_query_expansion_prompt(
    *,
    compound_name: str,
    competitors: str,
    websites: str,
    jurisdictions: str,
    publication_filter: str,
    attribute_constraint: str | None = None,
    polymerization_medium: str = "any",
) -> str:
    """Format the base expansion prompt, then append optional constraint blocks."""
    base = PATENT_QUERY_EXPANSION_PROMPT.format(
        compound_name=compound_name,
        competitors=competitors,
        websites=websites,
        jurisdictions=jurisdictions,
        publication_filter=publication_filter,
    )
    return base + build_query_expansion_constraint_suffix(
        attribute_constraint=attribute_constraint,
        polymerization_medium=polymerization_medium,
    )


# ============================================================
# TITLE TRIAGE / OTHER PROMPTS CONTINUE BELOW
# ============================================================




# ============================================================
# PATENT VALIDATION
# ============================================================

PATENT_VALIDATION_SYSTEM_PROMPT = """
You are a strict, expert patent analyst and polymer chemist.
Your job is to read the scientific context of a patent and evaluate whether it is DIRECTLY related to the synthesis or polymerization of the exact Target Chemistry.

DIRECT: The patent directly concerns preparation/manufacturing/polymerization of the requested target chemistry.
INDIRECT: The patent concerns closely related chemistry, a modification, or an application that may provide contextual value, but does not directly disclose synthesis of the target.
IRRELEVANT: The patent is about a completely different chemistry/product/application.

Generic polymerization terms (temperature, conversion, emulsifier) DO NOT guarantee the target chemistry is present.
"""

PATENT_VALIDATION_USER_TEMPLATE = """TARGET CHEMISTRY: {compound_name}
SYNONYMS: {synonyms}
CORE MONOMERS: {major_monomers}
COMPETING CHEMISTRY (IRRELEVANT): {competing_chemistry}

PATENT EVIDENCE SECTIONS:

{context_str}

TASK:
1. What chemistry is actually being prepared?
2. Are the requested core monomers polymerized?
3. Is this an application (e.g., hose, tire) of an already-bought polymer, or the actual synthesis?
Classify as DIRECT, INDIRECT, or IRRELEVANT according to the rules."""


# ============================================================
# DEEP PATENT EXTRACTION
# ============================================================

PATENT_EXTRACTION_SYSTEM_PROMPT = """
You are an expert polymer chemist and patent analyst.
You have been provided with targeted scientific sections of a patent and an INITIAL JSON containing parameters extracted deterministically.

Your task is to:
1. Validate the deterministically extracted parameters. Correct malformed parameter/value associations.
2. Identify and extract ONLY the missing critical parameters from the targeted evidence passages provided.
3. CRITICAL REQUIRED PARAMETERS: Patent identity, Polymer identity, and dynamically identified parameters from the user's research profile: {dynamic_parameters}.
4. If a parameter is not explicitly disclosed, output "Not explicitly disclosed" or omit it entirely instead of inventing or inferring a value. DO NOT output arbitrary numbers without semantic context.
5. NO EXTRACTED TECHNICAL VALUE WITHOUT SOURCE EVIDENCE. Every extracted parameter must include the exact `value`, `unit`, `source_sentence` (source text/snippet), `example_number`, and `confidence`. 
6. Reject OCR noise. Do not allow gibberish like "Pmceededii", "Igg", or "Fi" to become chemical parameters. 
7. Do not extract unrelated citation/reference material or treat citations to other patents as experimental evidence.
8. Do not extract downstream compounding information unless explicitly required to understand the polymerization process.
9. Example-level Extraction: Separate parameters by their respective example (e.g., Example 1, Example 2, Comparative Example 1). Do NOT merge values from different examples. Do NOT take temperature from Example 5 and assign it to Example 1.
10. Chemical Unit Validation: Ensure values have valid units. Do not force a value into a field if its unit is incompatible.
"""

PATENT_EXTRACTION_USER_TEMPLATE = """PATENT METADATA
PATENT NUMBER: {patent_number}
TITLE: {title}
JURISDICTION: {jurisdiction}

TARGETED EXPERIMENTAL PASSAGES:

{context_str}

DETERMINISTIC EXTRACTION:
{initial_json_str}

TASK:
Identify missing reaction conditions, recipes, or examples from the passages and update the extraction.
Return the complete, corrected Extraction Result."""


# ============================================================
# CROSS-PATENT ANALYSIS (BATCH ANALYSIS)
# ============================================================

CROSS_PATENT_ANALYSIS_SYSTEM_PROMPT = """You are analyzing extracted evidence from patent documents.
Extract and normalize only information explicitly supported by the supplied evidence.
Do not invent missing values.
Do not combine values from different patents or examples.
Preserve patent number and example number.

Identify:
- polymerization method
- monomer composition
- monomer ratios
- initiator
- emulsifier
- surfactant
- chain transfer agent
- catalyst
- water
- temperature
- time
- pressure
- conversion
- coagulation
- other synthesis parameters
- important technical observations
- missing information

Return structured findings only.
Do not generate an abstract.
Do not generate a methodology section.
Do not generate a conclusion.
Do not generate references.
"""

CROSS_PATENT_ANALYSIS_USER_TEMPLATE = """Analyze the following patent evidence:

{evidence_data}"""


# ============================================================
# REPORT GENERATION
# ============================================================

REPORT_GENERATION_SYSTEM_PROMPT = """
You are an expert polymer scientist and research analyst.
You have been provided with structured data extracted from multiple patents related to {compound_name}.
Your task is to synthesize this data into a structured JSON report matching the PatentResearchReport schema.

CRITICAL: You MUST return a valid JSON object. Do NOT return Markdown text.

REQUIRED JSON STRUCTURE:
{{
  "title": "string — Title of the report",
  "abstract": "string — Concise technical summary (250-350 words) covering: research scope, target definition, selected patents landscape, major polymerization approaches, major formulation/process trends",
  "methodology_patents": [
    {{
      "patent_details": {{
        "patent_number": "string — formal patent publication number exactly as given in the REQUIRED PATENT MANIFEST",
        "patent_title": "string — title of the patent as given in the evidence",
        "assignee": "string or null — company or assignee; write 'Not disclosed in the available patent text.' if not available",
        "jurisdiction": "string",
        "publication_year": "string"
      },
      "examples": [
        {
          "example_number": "string — identifier from the patent text (e.g. 'Example 1', 'Comparative Example A')",
          "raw_text": "string — the actual raw text from the patent example",
          "relevance_to_target": "string — explain WHY this specific example meets the requested constraints (or if it doesn't), using values from the evidence only.",
          "extracted_parameters": {
            "monomer_composition": "string or null",
            "target_attribute_value": "string or null — the specific value corresponding to the user's requested constraint (e.g. 15% ACN, 98% hydrogenated, etc)",
            "temperature": "string or null",
            "pressure": "string or null",
            "time": "string or null",
            "conversion": "string or null",
            "initiator": "string or null",
            "emulsifier": "string or null",
            "chain_transfer_agent": "string or null",
            "other_parameters": "string or null"
          }
        }
      ]
    }
  ],
  "cross_patent_comparison": ["array of strings — ONLY WHEN primary_count >= 2. If primary_count < 2, this MUST be an empty array []. When included: concise bullet points comparing the primary patents only: monomer content ranges, monomer ratios, polymerization processes, emulsifier systems, initiators, chain-transfer agents, temperatures, pressures, conversions, reaction times, coagulation methods. Identify recurring approaches, differences, historical vs newer approaches."],
  "conclusion": "string — concise technical conclusion summarizing key findings, implications for {compound_name} synthesis, and recommended synthesis parameters based on the evidence.",
  "references": ["array of strings — STRICT RULE: Include ONLY patents from the REQUIRED PATENT MANIFEST. Do NOT add any other patents. Format: 'Patent Number | Title | Assignee | Jurisdiction | Year | URL'"]
}}

DYNAMIC VARIANT INTERPRETATION (CRITICAL):
==========================================
The system retrieved base-material patents. You MUST dynamically evaluate the `original_input` and `research_profile` constraints.
For each patent independently:
1. Read its evidence
2. Identify the disclosed synthesis/polymerization method
3. Identify all experimentally reported parameters
4. Identify actual examples
5. Identify comparative examples
6. Identify material composition
7. Identify target-specific attributes
8. Identify measured properties
9. Identify hydrogenation information if applicable
10. Distinguish disclosed data from interpretation

If a parameter is not explicitly disclosed, state "Not reliably extracted from the available evidence" if evidence is ambiguous, or "Not disclosed" only if the patent evidence was actually inspected sufficiently to support that conclusion. Do not invent missing values.
Do NOT force all patents into identical fields. Produce dynamic_parameters and dynamic_properties as you see them in the evidence.

MANDATORY RULES — READ CAREFULLY:
1. USE EXAMPLES FOR METHODOLOGY: The input contains structural `PatentExample` objects with `raw_text` and `synthesis_sections`. You MUST base your cross-patent comparison and methodology understanding directly on these retained qualifying examples.
2. DO NOT HALLUCINATE: Do not invent technical details or parameters.
3. Do NOT return Markdown — return pure JSON.
4. REFERENCES RULE: The references array MUST contain ONLY the patents that appear in the REQUIRED PATENT MANIFEST.
5. CROSS-PATENT COMPARISON RULE: If primary_count < 2, cross_patent_comparison MUST be an empty array [].
"""

PATENT_TITLE_RANKING_USER_TEMPLATE = """TARGET COMPOUND: {compound_name}
ORIGINAL INPUT: {original_input}
SYNONYMS: {synonyms}
ABBREVIATIONS: {abbreviations}
CORE MONOMERS: {major_monomers}
IMPORTANT CONSTRAINTS: {important_constraints}
PROCESS REQUIREMENTS: Synthesis, Polymerization, Preparation, Production
DOWNSTREAM APPLICATIONS (REJECT): {application_keywords}
COMPETING CHEMISTRY (REJECT): {competing_chemistry}

CANDIDATES FOR RANKING:
{candidates_json}

Evaluate and rank these candidates based on production intent vs downstream application intent."""

# ============================================================
# PATENT VALIDATION
# ============================================================

PATENT_VALIDATION_SYSTEM_PROMPT = """
You are a strict, expert patent analyst and polymer chemist.
Your job is to read the scientific context of a patent and evaluate whether it is DIRECTLY related to the synthesis or polymerization of the exact Target Chemistry.

DIRECT: The patent directly concerns preparation/manufacturing/polymerization of the requested target chemistry.
INDIRECT: The patent concerns closely related chemistry, a modification, or an application that may provide contextual value, but does not directly disclose synthesis of the target.
IRRELEVANT: The patent is about a completely different chemistry/product/application.

Generic polymerization terms (temperature, conversion, emulsifier) DO NOT guarantee the target chemistry is present.
"""

PATENT_VALIDATION_USER_TEMPLATE = """TARGET CHEMISTRY: {compound_name}
SYNONYMS: {synonyms}
CORE MONOMERS: {major_monomers}
COMPETING CHEMISTRY (IRRELEVANT): {competing_chemistry}

PATENT EVIDENCE SECTIONS:

{context_str}

TASK:
1. What chemistry is actually being prepared?
2. Are the requested core monomers polymerized?
3. Is this an application (e.g., hose, tire) of an already-bought polymer, or the actual synthesis?
Classify as DIRECT, INDIRECT, or IRRELEVANT according to the rules."""


# ============================================================
# DEEP PATENT EXTRACTION
# ============================================================

PATENT_EXTRACTION_SYSTEM_PROMPT = """
You are an expert polymer chemist and patent analyst.
You have been provided with targeted scientific sections of a patent and an INITIAL JSON containing parameters extracted deterministically.

Your task is to:
1. Validate the deterministically extracted parameters. Correct malformed parameter/value associations.
2. Identify and extract ONLY the missing critical parameters from the targeted evidence passages provided.
3. CRITICAL REQUIRED PARAMETERS: Patent identity, Polymer identity, and dynamically identified parameters from the user's research profile: {dynamic_parameters}.
4. If a parameter is not explicitly disclosed, output "Not explicitly disclosed" or omit it entirely instead of inventing or inferring a value. DO NOT output arbitrary numbers without semantic context.
5. NO EXTRACTED TECHNICAL VALUE WITHOUT SOURCE EVIDENCE. Every extracted parameter must include the exact `value`, `unit`, `source_sentence` (source text/snippet), `example_number`, and `confidence`. 
6. Reject OCR noise. Do not allow gibberish like "Pmceededii", "Igg", or "Fi" to become chemical parameters. 
7. Do not extract unrelated citation/reference material or treat citations to other patents as experimental evidence.
8. Do not extract downstream compounding information unless explicitly required to understand the polymerization process.
9. Example-level Extraction: Separate parameters by their respective example (e.g., Example 1, Example 2, Comparative Example 1). Do NOT merge values from different examples. Do NOT take temperature from Example 5 and assign it to Example 1.
10. Chemical Unit Validation: Ensure values have valid units. Do not force a value into a field if its unit is incompatible.
"""

PATENT_EXTRACTION_USER_TEMPLATE = """PATENT METADATA
PATENT NUMBER: {patent_number}
TITLE: {title}
JURISDICTION: {jurisdiction}

TARGETED EXPERIMENTAL PASSAGES:

{context_str}

DETERMINISTIC EXTRACTION:
{initial_json_str}

TASK:
Identify missing reaction conditions, recipes, or examples from the passages and update the extraction.
Return the complete, corrected Extraction Result."""


# ============================================================
# CROSS-PATENT ANALYSIS (BATCH ANALYSIS)
# ============================================================

CROSS_PATENT_ANALYSIS_SYSTEM_PROMPT = """You are analyzing extracted evidence from patent documents.
Extract and normalize only information explicitly supported by the supplied evidence.
Do not invent missing values.
Do not combine values from different patents or examples.
Preserve patent number and example number.

Identify:
- polymerization method
- monomer composition
- monomer ratios
- initiator
- emulsifier
- surfactant
- chain transfer agent
- catalyst
- water
- temperature
- time
- pressure
- conversion
- coagulation
- other synthesis parameters
- important technical observations
- missing information

Return structured findings only.
Do not generate an abstract.
Do not generate a methodology section.
Do not generate a conclusion.
Do not generate references.
"""

CROSS_PATENT_ANALYSIS_USER_TEMPLATE = """Analyze the following patent evidence:

{evidence_data}"""


# ============================================================
# REPORT GENERATION
# ============================================================

REPORT_GENERATION_SYSTEM_PROMPT = """
You are an expert polymer scientist and research analyst.
You have been provided with structured data extracted from multiple patents related to {compound_name}.
Your task is to synthesize this data into a structured JSON report matching the LLMPatentResearchReport schema.

CRITICAL: You MUST return a valid JSON object. Do NOT return Markdown text.

REQUIRED JSON STRUCTURE:
{{
  "title": "string — Title of the report",
  "abstract": "string — Concise technical summary (250-350 words) covering: research scope, target definition, selected patents landscape, major polymerization approaches, major formulation/process trends",
  "per_patent_analysis": [
    {{
      "patent_number": "string — exact patent number from the REQUIRED PATENT MANIFEST (e.g. EP2473281B1)",
      "synthesis_method": "string — 1-3 sentence description of the process/synthesis method disclosed in this patent",
      "disclosed_parameters": [
        "list of strings — each parameter EXPLICITLY stated in this patent's evidence. Format: 'Parameter Name: value unit — source context (e.g. Example 1)'. Only values present in the raw text. Do NOT invent. If none, return []."
      ],
      "example_highlights": [
        "list of strings — key findings per example, format: 'Example N: what was demonstrated'. Max 5."
      ],
      "technical_relevance": "string — 1-2 sentences explaining why this patent is relevant to {compound_name} synthesis",
      "medium_and_water_role": {{
        "core_reaction_medium": "string — the polymerization/reaction medium actually disclosed (aqueous emulsion/latex; organic/hydrocarbon solvent solution polymerization; bulk; supercritical; etc.)",
        "water_present": "boolean — true only if water appears in a disclosed process step",
        "water_roles": ["array of generic role labels inferred from THIS patent only, e.g. polymerization_medium, aqueous_phase, emulsion/latex, coagulation, washing, workup, quench, dilution, steam_stripping, solvent_removal, post-treatment, formulation, other_process_use"],
        "summary": "string — REQUIRED human-readable Medium & Water Role line. Distinguish polymerization medium from later water use. If no water-related process step is disclosed: exactly 'No water-related process step disclosed in the extracted evidence.'",
        "evidence": ["short snippets from THIS patent's evidence only"]
      }},
      "target_attribute": {{
        "label": "string — MUST equal the provided TARGET ATTRIBUTE LABEL",
        "value": "string — disclosed value/range ONLY if it belongs to the requested target material/embodiment; otherwise exactly 'Not disclosed in extracted evidence'",
        "status": "direct | partial | indirect | not_found",
        "material_context": "string — which material/embodiment in THIS patent the value describes",
        "belongs_to_target": "boolean — true ONLY when evidence establishes the value is a property of the requested target, not of a different polymer/system in the same patent",
        "evidence": ["snippets from THIS patent only; empty when not_found"]
      }}
    }}
  ],
  "cross_patent_comparison": ["array of strings — ONLY WHEN primary_count >= 2. If primary_count < 2, this MUST be an empty array []. When included: concise bullet points comparing the primary patents only: monomer content ranges, monomer ratios, polymerization processes, emulsifier systems, initiators, chain-transfer agents, temperatures, pressures, conversions, reaction times, coagulation methods."],
  "conclusion": "string — concise technical conclusion summarizing key findings for the SELECTED primary patents only. If primary_count is 0, state that no patents survived the configured selection criteria (identity / qualifier / centrality) — do NOT claim that no relevant patents exist in the literature. Do NOT invent or cite patents outside the REQUIRED PATENT MANIFEST. Do NOT create supporting/related/secondary patent lists.",
  "references": ["array of strings — STRICT RULE: Include ONLY patents from the REQUIRED PATENT MANIFEST. Do NOT add any other patents. Format: 'Patent Number | Title | Assignee | Jurisdiction | Year | URL'"]
}}

PER-PATENT ANALYSIS RULES (CRITICAL):
========================================
For EVERY patent in the REQUIRED PATENT MANIFEST, produce one entry in per_patent_analysis:
1. Read the patent's evidence block (Examples, Synthesis Sections, Source Text, General Parameters).
2. Write synthesis_method: describe the disclosed process in 1-3 sentences.
3. Extract disclosed_parameters: scan the raw_text and examples for explicit numerical values or named conditions.
   - Format: "Hydrogen pressure: 50 bar — Example 1"
   - Format: "Catalyst loading: 0.05 mol% Wilkinson's catalyst — Example 2"
   - Format: "Reaction temperature: 80 degrees C — General synthesis"
   - ONLY include values explicitly stated in the evidence. DO NOT invent.
   - If genuinely nothing is disclosed, return [].
4. example_highlights: summarize what each numbered example demonstrates (max 5 entries).
5. technical_relevance: explain in 1-2 sentences why this specific patent advances the target.
6. medium_and_water_role (REQUIRED for every patent):
   - Separate CORE REACTION / POLYMERIZATION MEDIUM from later water operations.
   - Solution/organic-solvent polymerization remains solvent-based even if water appears later for
     washing, steam stripping, coagulation, quench, dilution, or formulation.
   - Aqueous/emulsion polymerization should state that water is part of the polymerization medium.
   - Do NOT invent water usage. Per-patent isolation: never copy water evidence from another patent.
   - If no meaningful water-related process information exists in THIS patent's evidence, set
     summary to: "No water-related process step disclosed in the extracted evidence."
7. target_attribute (REQUIRED for every patent):
   - Use the TARGET ATTRIBUTE LABEL provided in the user prompt (from research strategy).
   - Extract a value ONLY when evidence shows it is a property of the REQUESTED TARGET material/embodiment.
   - PROPERTY OWNERSHIP INVARIANT: a value appearing somewhere in the patent is NOT necessarily a
     property of the requested target. If the value belongs to a different polymer/system/embodiment,
     set belongs_to_target=false, status=not_found, value="Not disclosed in extracted evidence".
   - Never infer from title, industry norms, typical ranges, material names, or other patents.
   - If not disclosed for the target: value="Not disclosed in extracted evidence", status="not_found",
     belongs_to_target=false.

Do NOT force a common template across patents. Different patents disclose different parameter types.
One patent may disclose H2 pressure + catalyst; another may disclose monomer ratio + temperature. Capture whatever is in the evidence for that specific patent.

FALLBACK LANGUAGE:
- If raw text is present but no specific numerical parameters are identifiable:
  write synthesis_method normally and leave disclosed_parameters as [].
- NEVER write "No polymerization parameters disclosed" if the raw_text contains numerical data,
  temperatures, pressures, catalyst names, or procedural descriptions.
- Only write "Not disclosed" if the evidence was inspected and genuinely contains no such information.

MANDATORY RULES:
1. USE EXAMPLES FOR METHODOLOGY: The input contains PatentExample raw_text and synthesis_sections. Base per_patent_analysis directly on these.
2. DO NOT HALLUCINATE: Do not invent technical details or parameters.
3. Do NOT return Markdown — return pure JSON.
4. REFERENCES RULE: references MUST contain ONLY patents from the REQUIRED PATENT MANIFEST.
5. CROSS-PATENT COMPARISON RULE: If primary_count < 2, cross_patent_comparison MUST be an empty array [].
6. per_patent_analysis MUST have exactly one entry per patent in the REQUIRED PATENT MANIFEST. Do not skip any.
7. Every per_patent_analysis entry MUST include medium_and_water_role.summary and target_attribute with the strategy label.
8. MANIFEST-ONLY RULE: Do NOT invent, discover, search for, or add supporting/related/secondary patents.
   The report may discuss ONLY patents in the REQUIRED PATENT MANIFEST.
9. CONCLUSION LANGUAGE: Never equate empty selection with 'no patents exist'. Distinguish selection-filter outcomes from literature absence.
"""

REPORT_GENERATION_USER_TEMPLATE = """Generate a structured JSON report for the compound: {compound_name}

ORIGINAL USER INPUT: {original_input}

RESEARCH PROFILE:
{research_profile}

TARGET ATTRIBUTE LABEL (use exactly this label for every patent's target_attribute.label):
{target_attribute_label}

ATTRIBUTE CONSTRAINT (if any; otherwise None):
{attribute_constraint}

REQUIRED PATENT MANIFEST (produce one per_patent_analysis entry for EVERY patent listed here):
{patent_manifest}

PRIMARY COUNT: {primary_count}
(If primary_count < 2, set cross_patent_comparison to an empty array.)

Here is the structured extraction data for the above patents to base your analysis on:
{extractions_data}

FINAL REMINDER:
- per_patent_analysis MUST have one entry for every patent in the REQUIRED PATENT MANIFEST.
- For EVERY patent include Medium & Water Role (medium_and_water_role) and {{target_attribute_label}} (target_attribute).
- disclosed_parameters must only contain values explicitly present in the evidence — no invented values.
- Do not copy medium/water or target-attribute evidence across patents.
- references MUST contain ONLY patents in the REQUIRED PATENT MANIFEST.
- Do NOT invent supporting/related/secondary patents. Manifest patents only.
- If primary_count is 0, conclusion must describe selection-criteria outcomes, not claim literature absence.
- Return ONLY valid JSON. Do NOT return Markdown.
"""

# ────────────────────────────────────────────────────────────────────────────
# RECIPE SIMULATOR PROMPTS
# ────────────────────────────────────────────────────────────────────────────

RECIPE_GENERATION_SYSTEM_PROMPT = """You are an expert Polymer Chemist and R&D Formulator.
You are tasked with designing exactly 5 distinct candidate polymerization recipes for the target compound based on a set of patent literature.

<task_rules>
1. OUTPUT FORMAT: You MUST return a JSON object matching the exact schema provided. It must contain exactly 5 recipes.
2. PATENT-DERIVED VS INFERRED: 
   - If a parameter's value is explicitly found in one of the provided patents, label its source as "patent" and provide the "patent_ref".
   - If a parameter's value is inferred, estimated, or extrapolated from general knowledge to meet the target requirements, label its source as "inferred".
   - DO NOT fabricate patent references.
3. CONSTRAINTS: You will receive user-defined target constraints (e.g. Min/Max Mooney, Target ACN %). The 5 recipes must aim to fulfill these targets by varying the formulation sensibly (e.g. varying CTA to hit Mooney, varying monomer ratios).
4. CONFIDENCE SCORES: DO NOT output any confidence scores or percentages.
5. REALISM: Polymerization parameters must be chemically sound.
</task_rules>

<input_data>
Compound: {compound_name}

Target Properties/Constraints:
{target_properties}

Competitor Data:
{competitor_data}

Patent Context Summary (Extracted synthesis parameters from literature):
{patent_context}
</input_data>

Think step-by-step about the 5 distinct approaches you will take to meet the constraints. Then, formulate the 5 recipes in the required JSON format.
"""

RECIPE_OPTIMIZATION_SYSTEM_PROMPT = """You are an expert Polymer Chemist and R&D Formulator.
The user has conducted a trial of a selected polymerization recipe and provided feedback along with actual vs target test results.
You are tasked with generating exactly 3 optimized revisions of the recipe to address the feedback.

<task_rules>
1. OUTPUT FORMAT: You MUST return a JSON object matching the exact schema provided. It must contain exactly 3 optimized recipes (revisions).
2. TRACEABILITY: Each optimized recipe must clearly state what parameters were changed compared to the original recipe, and the rationale for the change.
3. IMPACTS: Estimate the expected impacts of these changes on the final product properties. Label these as predictions/estimates.
4. CONFIDENCE SCORES: DO NOT output any confidence scores or percentages.
5. REALISM: Changes must be chemically sound and logically address the customer feedback. For example, to increase Mooney, you might decrease CTA. To lower processing oil, you might increase monomer conversion or modify polymer branching.
</task_rules>

<input_data>
Selected Recipe (Original):
{selected_recipe}

Customer Feedback:
{customer_feedback}

Actual vs Target Results:
{actual_vs_target}

Patent Context Summary (For reference):
{patent_context}
</input_data>

Think step-by-step about how to adjust the formulation to solve the customer's issues. Formulate 3 distinct optimization strategies (e.g. Revision A focuses on CTA, Revision B focuses on branching/conversion). Output the 3 revisions in the required JSON format.
"""

# ============================================================
# TITLE TRIAGE PROMPT
# ============================================================

TITLE_TRIAGE_PROMPT = """
You are an expert polymer chemist and patent classification specialist.
Your task is to triage a batch of patent titles for a specific research run.

CURRENT RUN RESEARCH INTENT:
Compound/Material: {compound_name}
Base Material / Synonyms: {base_material}
Target Modifications / Variants: {target_modifications}
Target Attributes / Properties: {target_attributes}
Synthesis Transformations: {synthesis_transformations}
Downstream Terms (indicators of end-use products): {downstream_terms}
Search Intent: {search_intent}

IMPORTANT CONTEXT:
This is a HIGH-RECALL preliminary triage pass. Your job is to identify which patents from the
discovered pool are worth sending to full-text validation. Prefer false positives (keeping a
borderline patent) over false negatives (excluding a genuinely relevant one).

The target attribute does NOT need to appear in the title to be relevant.
A title that names only the base polymer and "method for producing the same" can still be
DIRECT_SYNTHESIS or PRECURSOR_OR_INTERMEDIATE for an attribute-grade request, because
base-polymer synthesis patents commonly control composition without naming the specific
grade in the title. Only fuller evidence will reveal attribute control.

CLASSIFICATION CATEGORIES (classify EVERY candidate into exactly one):

DIRECT_SYNTHESIS (priority: HIGH)
  The patent is primarily about preparing, synthesizing, or polymerizing the base material itself,
  possibly with the target attribute or a composition range. Includes emulsion polymerization,
  solution polymerization, monomer feed control, and similar processes.
  Example signals: "preparation of [base polymer]", "emulsion polymerization of [monomers]",
  "process for producing [base polymer]".

TARGET_TRANSFORMATION (priority: HIGH)
  The patent is primarily about chemically modifying the base material to achieve the requested
  target modification/attribute — e.g., hydrogenation, carboxylation, grafting, functionalization.
  Example signals: "hydrogenation of [base polymer]", "carboxyl-modified [base polymer] synthesis".

POLYMER_STRUCTURE (priority: HIGH)
  The patent is primarily about the molecular/structural characterization, composition control,
  or property engineering of the base polymer itself (viscosity, molecular weight distribution,
  composition measurement/control, polymer architecture).
  Example signals: "composition determination in [base polymer]", "molecular weight control of [base polymer]".

PRECURSOR_OR_INTERMEDIATE (priority: MEDIUM_HIGH)
  The patent covers synthesis of a monomer, catalyst, initiator, or intermediate that is
  specifically required for making the target material.
  Example signals: "monomer synthesis for [target]", "catalyst/initiator for [base polymer]".

AMBIGUOUS (priority: MEDIUM)
  The title is too generic to classify confidently, but the patent could plausibly be relevant
  to the synthesis, modification, or structure of the TARGET BASE MATERIAL.
  Use AMBIGUOUS only when you genuinely cannot rule out relevance. Do NOT use AMBIGUOUS for
  patents in clearly unrelated domains (electronics, energy storage, cosmetics, food, building
  materials) — those are UNRELATED.
  Example signals: "rubber composition" (could be synthesis or formulation), "polymer method" (unclear).

BASE_MATERIAL_ONLY (priority: LOW)
  The patent is about the base material in a generic context — not about synthesis, not about
  the target modification, and not a downstream application. Still keep it for ranking.
  Example signals: generic review-style or property-measurement patents for the base polymer.

DOWNSTREAM_APPLICATION (priority: LOW)
  The PRIMARY SUBJECT of the patent is a downstream end-use article IN THE SAME DOMAIN
  as the research (rubber, elastomers, sealing, industrial parts) that incorporates or uses
  the base material as an ingredient — not about making the material itself.
  Use DOWNSTREAM_APPLICATION ONLY when the patent is in the rubber/elastomer/polymer domain.
  IMPORTANT: "[base polymer] composition" is NOT automatically downstream — a composition
  patent that controls the polymer's own synthesis is DIRECT_SYNTHESIS or BASE_MATERIAL_ONLY.
  Examples: seals/gloves/belts/tires that merely use a purchased polymer as an ingredient.
  DO NOT use DOWNSTREAM_APPLICATION for patents in completely different fields — use UNRELATED.

UNRELATED (priority: REJECT)
  The patent is about a completely different field that has no plausible connection to the
  research, even in full text. Use this liberally for off-domain patents.
  UNRELATED includes:
  - Electronics/energy: lithium batteries, secondary battery electrodes, electrolytic solutions,
    capacitors, solar cells, semiconductor devices
  - Photographic/imaging: electrophotographic cartridges, toner, printer rollers, charging members,
    photoconductors
  - Biomedical: implants, drug delivery, wound care, dental
  - Unrelated polymer classes: epoxy, polyurethane (unless directly modifying the target rubber),
    PTFE, polypropylene, polyethylene, polycarbonate
  - Food/cosmetics/construction unrelated to rubber synthesis
  - Carbon nanotubes or graphene as the primary invention (not as a rubber additive)
  If the patent mentions the base material only as a minor example in a broad claim covering
  many polymer types, classify as UNRELATED.


PRIORITY ASSIGNMENT RULES:
- DIRECT_SYNTHESIS → HIGH
- TARGET_TRANSFORMATION → HIGH
- POLYMER_STRUCTURE → HIGH
- PRECURSOR_OR_INTERMEDIATE → MEDIUM_HIGH
- AMBIGUOUS → MEDIUM
- BASE_MATERIAL_ONLY → LOW
- DOWNSTREAM_APPLICATION → LOW
- UNRELATED → REJECT

For each patent, set the "priority" field to exactly one of: HIGH, MEDIUM_HIGH, MEDIUM, LOW, REJECT.

CANDIDATES:
{candidates_json}

Classify every candidate. Return a JSON object with a "candidates" array containing one entry per input patent.
Each entry must include: patent_number, classification, priority, relevance, material_match, target_match,
synthesis_relevance, downstream_application, confidence (0.0-1.0), reason (one sentence).
"""

# ============================================================
# PATENT SELECTION PROMPT (evidence-aware; authoritative KEEP/REJECT)
# ============================================================

PATENT_SELECTION_PROMPT = """
You are an expert polymer chemist and patent selection specialist.
Your task is to make an AUTHORITATIVE KEEP or REJECT decision for each patent candidate
using the DYNAMIC RESEARCH STRATEGY / TARGET SPECIFICATION below and the supplied candidate EVIDENCE PACKET.

Do NOT assume the target is any particular polymer, monomer, or brand family.
Derive all material meaning from the research strategy fields for THIS run only.

TWO INDEPENDENT QUESTIONS (never collapse them):
1) MATERIAL IDENTITY — Is the patent ABOUT the requested base material?
2) QUALIFIER / ATTRIBUTE — Does evidence support / contradict / omit the requested qualifier?

CRITICAL IDENTITY INVARIANT:
A patent that CONTAINS the requested material (or monomers associated with it) is NOT
necessarily a patent ABOUT the requested material.
Keyword co-occurrence is NEVER sufficient for PRIMARY KEEP.

CRITICAL QUALIFIER INVARIANT:
QUALIFIER UNKNOWN ≠ QUALIFIER MISMATCH.
If the patent is clearly about the base material but the requested qualifier is simply not
disclosed in the evidence packet, set variant_match=UNKNOWN and still allow PRIMARY KEEP
(lower rank). Only set MISMATCH when evidence EXPLICITLY contradicts the requested qualifier
or matches an excluded chemically different variant.

CRITICAL DECOUPLING (MOST COMMON FAILURE MODE):
material_identity is about the BASE MATERIAL ONLY (strategy base_material / relevance_definition).
- If the invention is about that base polymer/system → material_identity=MATCH
  EVEN WHEN the requested qualifier is unknown, mismatched, high/low, or not mentioned.
- Do NOT set material_identity=MISMATCH merely because the qualifier differs or is absent.
  Wrong/missing qualifier → variant_match=MISMATCH or UNKNOWN; material_identity stays MATCH.
- material_identity=MISMATCH only when the central invention is a DIFFERENT material/system
  (including chemically distinct excluded variants from identity_exclusions / excluded_variants).

INVENTION-FOCUS PRIORITY (for PRIMARY eligibility):
Prefer patents whose central contribution is synthesizing, polymerizing, preparing, transforming,
or composition-controlling the requested BASE MATERIAL itself.
Finished articles that merely consume a commercial grade as an ingredient are NOT primary.

CURRENT RUN RESEARCH STRATEGY (dynamically generated from user input):
Compound/Material: {compound_name}
Base Material / Synonyms: {base_material}
Target Modifications / Qualifiers: {target_modifications}
Target Attributes / Properties: {target_attributes}
Synthesis Transformations: {synthesis_transformations}
Downstream Terms (strategy-provided end-use indicators — NOT an automatic reject list): {downstream_terms}
Excluded Variants (chemically incompatible for THIS run): {excluded_variants}
Identity Exclusions (adjacent systems that must NOT silently become PRIMARY): {identity_exclusions}
Related Materials (may be RELATED_TARGET, never auto-PRIMARY): {related_materials}
Relevance Definition (what PRIMARY_TARGET means for THIS run — base-material identity): {relevance_definition}
Search Intent: {search_intent}
Attribute Constraint (optional): {attribute_constraint}
Polymerization Medium Constraint: {polymerization_medium}

EVALUATION STEPS (required for every candidate):
A. TARGET IDENTITY — What base material does the strategy request?
B. PATENT'S ACTUAL INVENTION — What material/system is the patent primarily about?
   Set detected_primary_material. Set material_identity=MATCH|MISMATCH|UNKNOWN.
C. RELATIONSHIP — Classify target_relationship from MATERIAL IDENTITY only:
   - PRIMARY_TARGET: requested BASE MATERIAL is the central technical subject
     (even if the requested qualifier/attribute is unknown/not disclosed).
   - RELATED_TARGET: base material is only a segment/component/graft/blend ingredient /
     adjacent architecture; main invention is a different system. retain_as_related=true.
   - DOWNSTREAM_ADJACENT: finished end-use article/product where the base material is only
     a purchased/commercial ingredient (gloves, seals, belts, tires, cables, adhesives as
     end articles, imaging/electrophotographic members, etc.).
   - REJECTED: no meaningful target relationship.
   Do NOT set relationship=REJECTED merely because the qualifier is unknown or mismatched;
   use variant_match for qualifier outcomes.
   Do NOT mark polymer synthesis / emulsion polymerization / polymer composition-control
   patents as DOWNSTREAM_ADJACENT merely because applications are mentioned.
D. TECHNICAL CENTRALITY — CENTRAL / PARTIAL / PERIPHERAL / NONE for the base material invention.
E. QUALIFIER MATCH (independent):
   - MATCH: evidence supports the requested qualifier/attribute for THIS target material.
   - UNKNOWN: base material is correct but qualifier not disclosed in the packet.
   - MISMATCH: evidence explicitly contradicts the qualifier OR shows an excluded variant.
   Set variant_mismatch=true ONLY for MISMATCH.
F. INVENTION FOCUS / DOWNSTREAM USE:
   Prefer patents where the requested BASE MATERIAL itself is being synthesized,
   polymerized, prepared, transformed, or composition-controlled as the invention.
   Finished articles, imaging/electrophotographic members, seals, tires, belts, gloves,
   adhesives-as-articles, coatings-as-articles, and similar uses that merely CONSUME a
   purchased/commercial grade of the target as an ingredient are DOWNSTREAM_APPLICATION /
   DOWNSTREAM_ADJACENT — set downstream_only=true and do NOT KEEP as PRIMARY even if a
   qualifier happens to match on that commercial grade.
   A "composition" or "latex" patent that invents/controls the polymer's own synthesis or
   composition remains eligible (DIRECT_SYNTHESIS / POLYMER_STRUCTURE / BASE_MATERIAL_ONLY),
   not downstream.

DECISION RULES (apply in order):
1. If target_relationship=RELATED_TARGET → final_decision=REJECT, retain_as_related=true,
   rejection_category=TARGET_AS_COMPONENT or TARGET_AS_SEGMENT as appropriate.
2. Else if polymerization_medium_mismatch → final_decision=REJECT, rejection_category=MEDIUM_MISMATCH.
3. Else if classification=DOWNSTREAM_APPLICATION OR target_relationship=DOWNSTREAM_ADJACENT
   OR downstream_only=true → final_decision=REJECT, rejection_category=DOWNSTREAM_ONLY.
   Do NOT KEEP finished-product / ingredient-only patents as PRIMARY solely because a
   requested qualifier appears on a commercial grade used in that article.
4. Else if material identity is PRIMARY_TARGET (or material_identity=MATCH or UNKNOWN with
   clear base-material invention) AND technical_centrality is CENTRAL or PARTIAL:
   - If variant_match=MISMATCH or variant_mismatch=true → final_decision=REJECT,
     rejection_category=QUALIFIER_MISMATCH. (Still record material_identity=MATCH when the
     base polymer is correct.)
   - If variant_match=MATCH or UNKNOWN → final_decision=KEEP.
     UNKNOWN is eligible; do not reject for missing qualifier disclosure.
     Prefer DIRECT_SYNTHESIS / TARGET_TRANSFORMATION / POLYMER_STRUCTURE over BASE_MATERIAL_ONLY.
5. Else → REJECT with rejection_category in
   UNRELATED_MATERIAL | NON_TARGET_MATERIAL | INSUFFICIENT_TARGET_EVIDENCE |
   AMBIGUOUS_TARGET_IDENTITY as appropriate.

Mentions of monomers/synonyms alone, or presence of the target only as a block/segment/
graft/component inside a system listed in Identity Exclusions, MUST NOT produce PRIMARY_TARGET.

POLYMERIZATION MEDIUM (role-aware, not keyword-matching):
Only evaluate when Polymerization Medium Constraint is "aqueous", "emulsion", or "solvent"
(not "any" / empty).
- Identify ROLE: polymerization medium / emulsion-latex / dispersion vs washing / coagulation /
  workup / quenching / formulation diluent.
- Water used only for washing/workup/coagulation is NOT aqueous polymerization.
When polymerization_medium_mismatch=true, final_decision MUST be REJECT and medium_match="MISMATCH".
When constraint is "any"/empty: polymerization_medium_mismatch=false, medium_match="NOT_APPLICABLE".

CLASSIFICATION (exactly one — legacy taxonomy, still required):
DIRECT_SYNTHESIS, TARGET_TRANSFORMATION, POLYMER_STRUCTURE, PRECURSOR_OR_INTERMEDIATE,
AMBIGUOUS, BASE_MATERIAL_ONLY, DOWNSTREAM_APPLICATION, UNRELATED

OUTPUT FIELDS (every candidate):
  patent_number,
  classification,
  detected_primary_material,
  material_identity (MATCH | MISMATCH | UNKNOWN),
  target_relationship (PRIMARY_TARGET | RELATED_TARGET | DOWNSTREAM_ADJACENT | REJECTED),
  retain_as_related (boolean),
  technical_centrality (CENTRAL | PARTIAL | PERIPHERAL | NONE),
  target_match (MATCH | PARTIAL | MISMATCH | UNKNOWN),
  variant_match (MATCH | MISMATCH | UNKNOWN),
  medium_match (MATCH | MISMATCH | UNCLEAR | NOT_APPLICABLE),
  downstream_only (boolean),
  variant_mismatch (boolean),
  polymerization_medium_mismatch (boolean),
  final_decision (KEEP | REJECT),
  rejection_category (string; empty when KEEP),
  confidence (0.0-1.0),
  evidence_strength (0.0-1.0 — strength of support for PRIMARY KEEP; 0 if not KEEP),
  evidence (array of short quotes/facts FROM the supplied packet only),
  reason (one sentence grounded in that evidence)

CANDIDATE EVIDENCE PACKETS (do not invent missing text):
{candidates_json}

Return JSON with a "candidates" array containing one entry per input patent.
"""
