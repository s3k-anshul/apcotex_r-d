import re
import logging
from typing import Tuple, List
import yaml
import os

from app.services.pipeline.schemas import CompoundSearchProfile, EvidenceLedger, CandidateState, RelevanceClass, MetadataQualification

logger = logging.getLogger(__name__)

class RuleEngineService:
    def __init__(self):
        # Load YAML configuration
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "core", "filter_config.yaml")
        try:
            with open(config_path, "r") as f:
                self.config = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load filter_config.yaml: {e}")
            self.config = {}
            
        self.obvious_false_positives = self.config.get("obvious_false_positives", [
            "battery", "electrode", "lithium", "semiconductor", "oled", "medical device"
        ])

    def _normalize_text(self, text: str) -> str:
        """Strips hyphens, slashes, commas, and excessive spaces for normalized matching."""
        text = text.lower()
        text = re.sub(r'[-\/,_]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def evaluate_candidate_metadata(self, metadata: dict, ledger: EvidenceLedger, profile: CompoundSearchProfile):
        """
        Stage 2: Progressive Qualification on Serper Metadata.
        Enforces Hard Chemistry Identity (Part 4) and Synthesis Intent (Part 5).
        Modifies ledger in-place.
        """
        title = self._normalize_text(metadata.get("title", ""))
        snippet = self._normalize_text(metadata.get("snippet", ""))
        raw_text = f"{title} {snippet}"
        
        target_score = 0
        synthesis_score = 0
        penalty = 0
        
        # 1. Target Chemistry Identity Gate (Part 4 & Phase 2 Normalization)
        # Broadly match the compound name, synonyms, acronyms, and chemical family
        all_target_names = [profile.compound_name] + profile.synonyms + profile.abbreviations + [profile.chemical_family]
        for term in all_target_names:
            if not term:
                continue
            norm_term = self._normalize_text(term)
            if norm_term and norm_term in raw_text:
                target_score += 30 # Reduced from 50 so exact name alone doesn't dominate, but still passes threshold
                if term in profile.synonyms or term in profile.abbreviations:
                    ledger.dimensions.matched_synonyms.append(term)
                    ledger.log(f"Stage 2 (Chemistry): Found synonym/abbreviation '{term}' (+30)")
                elif term == profile.chemical_family:
                    ledger.dimensions.matched_chemistry_family.append(term)
                    ledger.log(f"Stage 2 (Chemistry): Found chemical family '{term}' (+30)")
                else:
                    ledger.dimensions.compound_evidence.append(f"Name Match: {term}")
                    ledger.log(f"Stage 2 (Chemistry): Found target name '{term}' (+30)")
                
        # Check core monomers
        if profile.major_monomers:
            monomers_found = sum(1 for m in profile.major_monomers if self._normalize_text(m) in raw_text)
            if monomers_found > 0:
                ledger.dimensions.matched_monomers.extend([m for m in profile.major_monomers if self._normalize_text(m) in raw_text])
                target_score += (20 * monomers_found)
                ledger.log(f"Stage 2 (Chemistry): Found {monomers_found} core monomers (+{20 * monomers_found})")

        # 2. Synthesis Intent vs Application Intent (Part 5)
        # High value synthesis terms
        for term in profile.typical_manufacturing_keywords + profile.manufacturing_keywords + profile.typical_polymerization_routes:
            norm_term = self._normalize_text(term)
            if norm_term in title:
                synthesis_score += 30
                ledger.dimensions.manufacturing_evidence.append(f"Title: {term}")
                ledger.log(f"Stage 2 (Synthesis): Found in Title '{term}' (+30)")
            elif norm_term in snippet:
                synthesis_score += 15
                ledger.dimensions.manufacturing_evidence.append(f"Snippet: {term}")
                ledger.log(f"Stage 2 (Synthesis): Found in Snippet '{term}' (+15)")

        # Low value application terms do not cause rejection, but we log them
        for term in profile.application_keywords:
            norm_term = self._normalize_text(term)
            if norm_term in raw_text:
                ledger.dimensions.negative_evidence.append(term)
                ledger.log(f"Stage 2 (Application): Found downstream term '{term}'")

        # 3. Competing Chemistry (Hard Penalty)
        for term in profile.competing_chemistry:
            norm_term = self._normalize_text(term)
            if norm_term and norm_term in raw_text:
                penalty += 100
                ledger.dimensions.competing_chemistry.append(term)
                ledger.log(f"Stage 2 (Competing): Found competing chemistry '{term}' (-100)")

        # 4. Obvious False Positive Penalties
        for term in self.obvious_false_positives:
            norm_term = self._normalize_text(term)
            if norm_term in raw_text:
                penalty += 100
                ledger.dimensions.negative_evidence.append(term)
                ledger.log(f"Stage 2 (Penalty): Found obvious false positive '{term}' (-100)")
                
        # 5. Compile Search Score
        ledger.dimensions.target_chemistry_score = target_score
        ledger.dimensions.synthesis_score = synthesis_score
        # We don't add these directly to search_confidence because overall_confidence uses them explicitly now
        ledger.dimensions.search_confidence -= penalty
        
        if penalty >= 100:
            ledger.qualification = MetadataQualification.REJECT
            # State is left as default (LOW) or unchanged, relevance governs eligibility
            ledger.rejection_reason = "Obvious false positive or competing chemistry found."
            ledger.log("Rejected: " + ledger.rejection_reason)
        elif target_score > 0 or synthesis_score > 0:
            ledger.qualification = MetadataQualification.KEEP
            ledger.log(f"Qualification -> KEEP (Target: {target_score}, Synthesis: {synthesis_score})")
        else:
            ledger.qualification = MetadataQualification.REVIEW
            ledger.log(f"Qualification -> REVIEW (Target: {target_score}, Synthesis: {synthesis_score})")

    def score_content(self, parsed_patent, profile: CompoundSearchProfile, ledger: EvidenceLedger):
        """
        Stage 4 & 5: BeautifulSoup Structural Analysis and Recipe Confidence.
        """
        evidence = parsed_patent.structural_evidence
        
        # Calculate Recipe Score based on Structural Evidence counts
        recipe_score = 0
        
        if evidence.example_count > 0:
            recipe_score += 40
            ledger.log(f"Stage 5 (Recipe): Found {evidence.example_count} Examples (+40)")
            
        if evidence.table_count > 0:
            recipe_score += 20
            ledger.log(f"Stage 5 (Recipe): Found {evidence.table_count} Tables (+20)")
            
        if evidence.temperature_count > 0 or evidence.pressure_count > 0:
            recipe_score += 30
            ledger.log("Stage 5 (Recipe): Found Reaction Conditions (+30)")
            
        entity_count = (evidence.initiator_count + evidence.emulsifier_count + 
                        evidence.chain_transfer_count + evidence.conversion_count + 
                        evidence.coagulation_count)
                        
        if entity_count > 0:
            recipe_score += 25
            ledger.log(f"Stage 5 (Recipe): Found {entity_count} Recipe Entities (+25)")
            
        if evidence.has_preparation_example or evidence.has_experimental_example:
            recipe_score += 20
            ledger.log("Stage 5 (Recipe): Found Reaction Sequence Headers (+20)")
            
        ledger.dimensions.recipe_score = recipe_score
        
        # Full Content Verification (Stage B)
        full_text = self._normalize_text(
            (parsed_patent.abstract or "") + " " + 
            (parsed_patent.detailed_description or "") + " " + 
            (parsed_patent.examples or "")
        )
        
        target_score = 0
        all_target_names = [profile.compound_name] + profile.synonyms + profile.abbreviations + [profile.chemical_family]
        for term in all_target_names:
            if not term:
                continue
            norm_term = self._normalize_text(term)
            if norm_term and norm_term in full_text:
                target_score += 30
                ledger.log(f"Stage 4 (Chemistry): Found term '{term}' in full patent (+30)")
                
        if profile.major_monomers:
            monomers_found = sum(1 for m in profile.major_monomers if self._normalize_text(m) in full_text)
            if monomers_found > 0:
                target_score += (20 * monomers_found)
                ledger.log(f"Stage 4 (Chemistry): Found {monomers_found} core monomers in full patent (+{20 * monomers_found})")

        synthesis_score = 0
        for term in profile.typical_manufacturing_keywords + profile.manufacturing_keywords + profile.typical_polymerization_routes:
            if self._normalize_text(term) in full_text:
                synthesis_score += 30

        penalty = 0
        for term in profile.competing_chemistry:
            if self._normalize_text(term) in full_text:
                penalty += 100
                ledger.log(f"Stage 4 (Penalty): Competing chemistry '{term}' found in full patent")
                
        # Application penalty applies only if NO synthesis/recipe score exists (Downstream-only penalty)
        application_penalty = 0
        if recipe_score < 20 and synthesis_score < 30:
            for term in profile.application_keywords:
                if self._normalize_text(term) in full_text:
                    application_penalty += 50
                    ledger.log(f"Stage 4 (Application Penalty): Downstream term '{term}' without upstream synthesis (-50)")
                
        ledger.dimensions.target_chemistry_score = max(ledger.dimensions.target_chemistry_score, target_score)
        ledger.dimensions.synthesis_score = max(ledger.dimensions.synthesis_score, synthesis_score)
        
        # Adjust overall confidence logically
        ledger.dimensions.recipe_score = recipe_score
        
        # We no longer force IRRELEVANT just because target_chemistry_score == 0
        # If the patent has high recipe_score and synthesis_score, maybe the chemical wasn't parsed well but it's valid
        if penalty >= 100:
            ledger.relevance = RelevanceClass.IRRELEVANT
            ledger.log("Final Content Relevance -> IRRELEVANT (Competing chemistry found)")
        elif application_penalty > 0 and ledger.dimensions.synthesis_score < 30 and recipe_score < 20:
             ledger.relevance = RelevanceClass.IRRELEVANT
             ledger.log("Final Content Relevance -> IRRELEVANT (Downstream application only with no synthesis)")
        elif ledger.dimensions.target_chemistry_score >= 20 and (ledger.dimensions.synthesis_score >= 15 or recipe_score >= 20):
            ledger.relevance = RelevanceClass.DIRECT
            ledger.log("Final Content Relevance -> DIRECT")
        else:
            ledger.relevance = RelevanceClass.INDIRECT
            ledger.log("Final Content Relevance -> INDIRECT")

        ledger.state = CandidateState.STRONG if ledger.dimensions.overall_confidence >= 80 else CandidateState.REVIEW
        ledger.log(f"Stage 5 (Recipe): Final Structural Score: {ledger.dimensions.overall_confidence}")

    def evaluate_candidate_relevance(self, metadata: dict, ledger: EvidenceLedger, profile: CompoundSearchProfile, queries: list):
        """
        Stage 5: Deterministic Validity Gate & Relevance Scoring on Lightweight Metadata.
        """
        title = metadata.get("google_patents_title") or metadata.get("title", "")
        abstract = metadata.get("abstract", "")
        claims = metadata.get("claims", "")
        
        norm_title = self._normalize_text(title)
        norm_abstract = self._normalize_text(abstract)
        norm_claims = self._normalize_text(claims)
        
        full_text = f"{norm_title} {norm_abstract} {norm_claims}"
        
        # 0. Legal Status Gate
        status = metadata.get("legal_status", "").upper()
        if status in ["EXPIRED", "ABANDONED", "WITHDRAWN", "DEAD", "CEASED", "LAPSED"]:
            metadata["eligibility"] = "REJECTED"
            metadata["rejection_reason"] = f"LEGAL_STATUS_{status}"
            ledger.log(f"Gate (Reject): Legal status is {status}")
            return 0
        
        # 1. Target Chemistry
        target_score = 0
        all_target_names = [profile.compound_name] + profile.synonyms + profile.abbreviations + [profile.chemical_family]
        for term in all_target_names:
            if not term:
                continue
            norm_term = self._normalize_text(term)
            if norm_term and norm_term in full_text:
                target_score += 30
                ledger.log(f"Gate (Chemistry): Found target name '{term}' (+30)")
                break
                
        if profile.major_monomers:
            monomers_found = sum(1 for m in profile.major_monomers if self._normalize_text(m) in full_text)
            if monomers_found > 0:
                target_score += (20 * monomers_found)
                ledger.log(f"Gate (Chemistry): Found {monomers_found} core monomers (+{20 * monomers_found})")
        target_score = min(30, target_score)
                
        # 2. Polymerization Intent
        poly_score = 0
        poly_terms = ["polymerization", "polymerisation", "copolymerization", "preparation", "preparing", "production", "producing", "manufacturing", "manufacture", "synthesis", "process for producing", "process for preparing", "method for producing", "method for preparing", "emulsion polymerization", "solution polymerization", "suspension polymerization"]
        for term in profile.typical_manufacturing_keywords + profile.manufacturing_keywords + profile.typical_polymerization_routes + poly_terms:
            if self._normalize_text(term) in full_text:
                poly_score += 25
                ledger.log(f"Gate (Synthesis): Found '{term}' (+25)")
                break
        poly_score = min(25, poly_score)
                
        # 3. Competing Chemistry & Application Penalties
        penalty = 0
        rejection_reason = ""
        
        for term in profile.competing_chemistry:
            if self._normalize_text(term) in full_text:
                rejection_reason = "COMPETING_POLYMER"
                ledger.log(f"Gate (Reject): Found competing chemistry '{term}'")
                break
                
        if not rejection_reason:
            for term in self.obvious_false_positives:
                if self._normalize_text(term) in full_text:
                    rejection_reason = "FALSE_POSITIVE"
                    ledger.log(f"Gate (Reject): Found obvious false positive '{term}'")
                    break

        if not rejection_reason:
            pyrolysis_terms = ["pyrolysis", "depolymerization", "polymer degradation", "recycling", "thermal cracking", "catalytic cracking", "polymer decomposition"]
            for term in pyrolysis_terms:
                if self._normalize_text(term) in full_text:
                    rejection_reason = "PYROLYSIS_OR_DEGRADATION"
                    ledger.log(f"Gate (Reject): Found degradation term '{term}'")
                    break

        # Mandatory Validity Gate
        if rejection_reason:
            metadata["eligibility"] = "REJECTED"
            metadata["rejection_reason"] = rejection_reason
            return 0
            
        if target_score == 0:
            metadata["eligibility"] = "REJECTED"
            metadata["rejection_reason"] = "TARGET_CHEMISTRY_MISMATCH"
            ledger.log("Gate (Reject): No target chemistry found")
            return 0
            
        if poly_score == 0:
            metadata["eligibility"] = "REJECTED"
            metadata["rejection_reason"] = "NO_POLYMERIZATION_RELEVANCE"
            ledger.log("Gate (Reject): No polymerization relevance found")
            return 0
            
        # Optional Penalties for downstream terms (but not immediate rejection if synthesis is present)
        for term in profile.application_keywords:
            if self._normalize_text(term) in norm_title: 
                penalty += 30
                ledger.log(f"Gate (Application Penalty): Found downstream term '{term}' in title (-30)")
            elif self._normalize_text(term) in full_text:
                penalty += 10
                ledger.log(f"Gate (Application Penalty): Found downstream term '{term}' (-10)")
                
        # 4. Target Range Relevance
        range_score = 0
        if getattr(profile, "target_composition_range", "") and getattr(profile, "target_composition_keywords", []):
            keywords = profile.target_composition_keywords
            for kw in keywords:
                norm_kw = self._normalize_text(kw)
                if norm_kw in full_text:
                    # Look for number + %/wt within ~50 characters of the keyword
                    # e.g., "acrylonitrile content of 20 to 30 wt%"
                    pattern = rf"({re.escape(norm_kw)}.{0,50}\d+\.?\d*\s*(%|wt|weight|parts|phr))|(\d+\.?\d*\s*(%|wt|weight|parts|phr).{0,50}{re.escape(norm_kw)})"
                    if re.search(pattern, full_text, flags=re.IGNORECASE):
                        range_score = 15
                        ledger.log(f"Gate (Range): Found potential composition range for {kw} (+15)")
                        break
                            
        # 5. Query / Title Relevance
        best_q = ""
        best_sim = 0.0
        title_tokens = set(norm_title.split())
        if title_tokens:
            for q in queries:
                q_text = self._normalize_text(q.get("query", ""))
                q_text = re.sub(r'^(ti|tac)\s+(.*)$', r'\2', q_text, flags=re.IGNORECASE)
                q_text = re.sub(r'^(ti|tac)=\((.*)\)$', r'\2', q_text, flags=re.IGNORECASE)
                q_tokens = set(q_text.split())
                if not q_tokens:
                    continue
                intersection = title_tokens.intersection(q_tokens)
                union = title_tokens.union(q_tokens)
                sim = len(intersection) / len(union) if union else 0
                if sim > best_sim:
                    best_sim = sim
                    best_q = q.get("query", "")
                    
        query_score = int(best_sim * 15)
        
        # 6. Recipe Signal Score
        recipe_score = 0
        recipe_signals = ["monomer", "initiator", "emulsifier", "surfactant", "chain transfer agent", "mercaptan", "thiol", "persulfate", "hydroperoxide", "conversion", "latex", "coagulation", "reaction"]
        for sig in recipe_signals:
            if self._normalize_text(sig) in full_text:
                recipe_score += 2
        recipe_score = min(10, recipe_score)
        
        # Calculate Final Score
        # Max scores: Target(30) + Poly(25) + Range(15) + Query(15) + Recipe(10) + Claims(5) = 100
        
        claims_score = 0
        if norm_claims:
            for term in all_target_names:
                if term and self._normalize_text(term) in norm_claims:
                    claims_score = 5
                    ledger.log(f"Gate (Claims): Found target name '{term}' in claims (+5)")
                    break
        
        total_score = target_score + poly_score + range_score + query_score + recipe_score + claims_score - penalty
        total_score = max(0, min(100, total_score))
        
        if total_score < 30: # MIN_PATENT_RELEVANCE_SCORE
            metadata["eligibility"] = "REJECTED"
            metadata["rejection_reason"] = "LOW_RELEVANCE_SCORE"
            ledger.log(f"Gate (Reject): Score {total_score} is below threshold 30")
            return 0
            
        metadata["eligibility"] = "KEEP"
        metadata["target_chemistry_score"] = target_score
        metadata["polymerization_score"] = poly_score
        metadata["target_range_score"] = range_score
        metadata["title_query_score"] = query_score
        metadata["recipe_signal_score"] = recipe_score
        metadata["claims_score"] = claims_score
        metadata["negative_score"] = penalty
        metadata["final_relevance_score"] = total_score
        metadata["best_matching_query"] = best_q
        metadata["best_query_similarity"] = best_sim
        
        ledger.dimensions.target_chemistry_score = max(ledger.dimensions.target_chemistry_score, target_score)
        ledger.dimensions.synthesis_score = max(ledger.dimensions.synthesis_score, poly_score)
        ledger.log(f"Title/Metadata Rank: Final Score {total_score} (Chem:{target_score}, Poly:{poly_score}, Range:{range_score}, Q:{query_score}, Recipe:{recipe_score}, Pen:{penalty})")
        
        return total_score
