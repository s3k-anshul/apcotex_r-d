"""
app/services/pipeline/search_service.py

Uses Gemini to generate a search strategy, then uses Serper API to find patent links.
Restored to use /search endpoint instead of /patents.
"""
import json
import logging
import re
from typing import List, Dict, Any

import httpx

from app.core.config import settings
from app.services.pipeline.schemas import LLMCompoundSearchProfile, GeneratedQuery
from app.services.llm import llm_client
from app.services.usage_logger import UsageLogger
from app.services.prompts.patent_prompts import build_query_expansion_prompt

logger = logging.getLogger(__name__)

class SerperCreditsExhaustedError(Exception):
    """Raised when Serper API returns 'Not enough credits' error."""
    pass


class SearchService:
    def __init__(self):
        self.serper_api_key = settings.SERPER_API_KEY

    async def generate_strategy(
        self, 
        compound_name: str, 
        competitors: List[str] = None,
        websites: List[str] = None,
        jurisdictions: List[str] = None,
        publication_filter: dict = None,
        attribute_constraint: str | None = None,
        polymerization_medium: str = "any",
    ) -> LLMCompoundSearchProfile:
        """Use Gemini to create the search strategy."""
        logger.info("Generating search strategy for %s...", compound_name)
        medium = (polymerization_medium or "any").strip().lower()
        logger.info(
            "[QUERY_EXPANSION] Optional constraints: "
            "attribute_constraint=%r polymerization_medium=%r",
            attribute_constraint,
            medium,
        )
        comp_str = ", ".join(competitors) if competitors else "None"
        web_str = ", ".join(websites) if websites else "None"
        jur_str = ", ".join(jurisdictions) if jurisdictions else "None"
        pub_str = str(publication_filter) if publication_filter else "None"
        
        prompt = build_query_expansion_prompt(
            compound_name=compound_name,
            competitors=comp_str,
            websites=web_str,
            jurisdictions=jur_str,
            publication_filter=pub_str,
            attribute_constraint=attribute_constraint,
            polymerization_medium=medium,
        )

        try:
            result, provider, usage = await llm_client.generate_structured(
                prompt=prompt,
                system_prompt="You are a JSON generator. Do not include markdown blocks.",
                schema=LLMCompoundSearchProfile,
                temperature=0.3
            )
            if not result:
                raise Exception("LLM Client returned None for structured extraction.")
            
            logger.info("[QUERY_EXPANSION] Target compound: %s", compound_name)
            logger.info("[QUERY_EXPANSION] Base material: %s", getattr(result, "base_material", ""))
            logger.info(
                "[QUERY_EXPANSION] Target identity: exclusions=%s related=%s definition=%s",
                getattr(result, "identity_exclusions", []),
                getattr(result, "related_materials", []),
                (getattr(result, "relevance_definition", "") or "")[:200],
            )
            logger.info("[QUERY_EXPANSION] Target modification: %s", getattr(result, "target_modifications", ""))
            
            validated_queries = []
            rejected_queries = 0
            
            # The A-G Validation rules
            for i, generated_query in enumerate(result.search_queries):
                q = generated_query.query
                q_lower = q.lower()
                logger.info("[QUERY_EXPANSION] Query %02d:", i + 1)
                logger.info("  Expression: %s", q)
                logger.info("  Scope: %s", generated_query.scope)
                logger.info("  Required: %s", generated_query.required_concepts)
                logger.info("  Alternatives: %s", generated_query.alternative_concepts)
                
                # Validation checks
                # A. Contains target/base-material concept
                has_base_in_query = False
                for base in result.base_material:
                    if base.lower() in q_lower:
                        has_base_in_query = True
                        break
                
                # B. Contains target modification/attribute when required.
                # Two-pass: (i) literal substring match of any target_modification phrase
                # in the query string; (ii) concept-overlap: any token from the query's
                # own required_concepts or alternative_concepts overlaps with the tokens
                # of the LLM's target_modification phrases for this run.
                # This avoids false rejection of queries that describe the same target
                # attribute using alternate scientific phrasing vs the literal LLM attribute string.
                has_target_mod_in_query = True
                if result.target_modifications:
                    has_target_mod_in_query = False

                    # Pass (i): literal phrase present in query string
                    for mod in result.target_modifications:
                        if mod.lower() in q_lower:
                            has_target_mod_in_query = True
                            break

                    if not has_target_mod_in_query:
                        # Pass (ii): concept-overlap — extract meaningful tokens
                        # (≥4 chars) from target_modification phrases, then check
                        # whether any of those tokens appears in required_concepts
                        # or alternative_concepts of the generated query.
                        mod_tokens = set()
                        for mod in result.target_modifications:
                            for tok in re.findall(r'\b[a-zA-Z]{4,}\b', mod.lower()):
                                mod_tokens.add(tok)

                        query_concept_words = set()
                        for concept in (generated_query.required_concepts + generated_query.alternative_concepts):
                            for tok in re.findall(r'\b[a-zA-Z]{4,}\b', concept.lower()):
                                query_concept_words.add(tok)

                        if mod_tokens and mod_tokens.intersection(query_concept_words):
                            has_target_mod_in_query = True

                        # Pass (iii): fallback — check if any mod_token appears as a
                        # word-boundary match in the query string itself (catches cases
                        # where required_concepts are not fully populated by LLM).
                        if not has_target_mod_in_query and mod_tokens:
                            for tok in mod_tokens:
                                if re.search(r'\b' + re.escape(tok) + r'\b', q_lower):
                                    has_target_mod_in_query = True
                                    break

                            
                # Check for bad flat OR statements across required boundaries
                # A heuristic check: if the query uses " OR " at the top level between a base material and a modification.
                # In google patents, OR should be inside parentheses.
                flat_or_bad = False
                if " or " in q_lower:
                    # if there are ORs outside parentheses, it might be a flat bag
                    # count opening and closing parens
                    if "(" not in q_lower and ")" not in q_lower:
                        flat_or_bad = True
                
                # E. No query is only generic process terminology
                is_only_generic = False
                if not has_base_in_query and not has_target_mod_in_query:
                    is_only_generic = True
                    
                if not has_base_in_query:
                    logger.info("  Boolean validation: FAIL (No base material concept)")
                    rejected_queries += 1
                elif flat_or_bad:
                    logger.info("  Boolean validation: FAIL (Top-level OR used inappropriately / flat keyword bag)")
                    rejected_queries += 1
                elif is_only_generic:
                    logger.info("  Boolean validation: FAIL (Generic terminology only)")
                    rejected_queries += 1
                else:
                    logger.info("  Boolean validation: PASS")
                    validated_queries.append(generated_query)
            
            TARGET_QUERY_COUNT = 15

            if len(validated_queries) < TARGET_QUERY_COUNT:
                missing_count = TARGET_QUERY_COUNT - len(validated_queries)
                logger.info(
                    "[QUERY_VALIDATION] Only %d valid queries from first LLM call (%d rejected). "
                    "Retrying LLM for %d additional distinct queries.",
                    len(validated_queries), rejected_queries, missing_count
                )

                # Build a retry prompt describing exactly what's needed
                existing_exprs = [q.query for q in validated_queries]
                retry_prompt = (
                    build_query_expansion_prompt(
                        compound_name=compound_name,
                        competitors=comp_str,
                        websites=web_str,
                        jurisdictions=jur_str,
                        publication_filter=pub_str,
                        attribute_constraint=attribute_constraint,
                        polymerization_medium=medium,
                    )
                    + f"\n\nNOTE: A previous call already produced {len(validated_queries)} valid queries. "
                    f"You MUST produce {missing_count} ADDITIONAL distinct valid Boolean queries that "
                    f"are NOT equivalent to any of these already-generated queries:\n"
                    + "\n".join(f"  - {e}" for e in existing_exprs)
                    + "\nDo NOT repeat or paraphrase any query from the list above."
                )

                try:
                    retry_result, _, _ = await llm_client.generate_structured(
                        prompt=retry_prompt,
                        system_prompt="You are a JSON generator. Do not include markdown blocks.",
                        schema=LLMCompoundSearchProfile,
                        temperature=0.5
                    )
                    if retry_result and retry_result.search_queries:
                        existing_query_strings = {q.query.strip().lower() for q in validated_queries}
                        # Pre-compute mod_tokens for the retry validation (same as primary pass)
                        retry_mod_tokens = set()
                        for mod in result.target_modifications:
                            for tok in re.findall(r'\b[a-zA-Z]{4,}\b', mod.lower()):
                                retry_mod_tokens.add(tok)

                        for gq in retry_result.search_queries:
                            if gq.query.strip().lower() in existing_query_strings:
                                logger.info("[QUERY_RETRY] Duplicate skipped: %s", gq.query)
                                continue
                            # Apply same A–B 3-pass validation
                            q_lower = gq.query.lower()
                            base_ok = any(b.lower() in q_lower for b in result.base_material)
                            flat_or_bad = (" or " in q_lower and "(" not in q_lower and ")" not in q_lower)
                            mod_ok = True
                            if result.target_modifications:
                                mod_ok = any(m.lower() in q_lower for m in result.target_modifications)
                                if not mod_ok and retry_mod_tokens:
                                    retry_concept_words = set()
                                    for concept in (gq.required_concepts + gq.alternative_concepts):
                                        for tok in re.findall(r'\b[a-zA-Z]{4,}\b', concept.lower()):
                                            retry_concept_words.add(tok)
                                    if retry_mod_tokens.intersection(retry_concept_words):
                                        mod_ok = True
                                if not mod_ok and retry_mod_tokens:
                                    for tok in retry_mod_tokens:
                                        if re.search(r'\b' + re.escape(tok) + r'\b', q_lower):
                                            mod_ok = True
                                            break
                            if base_ok and mod_ok and not flat_or_bad:
                                validated_queries.append(gq)
                                existing_query_strings.add(gq.query.strip().lower())
                                logger.info("[QUERY_RETRY] Accepted: %s", gq.query)
                            if len(validated_queries) >= TARGET_QUERY_COUNT:
                                break
                except Exception as retry_err:
                    logger.warning("[QUERY_RETRY] Retry LLM call failed: %s", retry_err)

            # Final deduplication by query string (regardless of source)
            seen_q_strings: set[str] = set()
            deduped_queries = []
            for gq in validated_queries:
                key = gq.query.strip().lower()
                if key not in seen_q_strings:
                    seen_q_strings.add(key)
                    deduped_queries.append(gq)
                else:
                    logger.info("[QUERY_DEDUP] Removed duplicate: %s", gq.query)

            if len(deduped_queries) < TARGET_QUERY_COUNT:
                logger.warning(
                    "[QUERY_VALIDATION] Proceeding with %d distinct queries "
                    "(target=%d; LLM did not return additional valid distinct queries after 1 retry).",
                    len(deduped_queries), TARGET_QUERY_COUNT
                )
            else:
                logger.info("[QUERY_VALIDATION] Final distinct query count: %d", len(deduped_queries))

            result.search_queries = deduped_queries

            return result
        except Exception as e:
            if type(e).__name__ == "ProviderExhaustedException":
                raise e
            logger.error("Failed to generate search strategy: %s", e, exc_info=True)
            return LLMCompoundSearchProfile(
                original_input=compound_name,
                search_queries=[GeneratedQuery(
                    query=f'("{compound_name}") AND polymerization',
                    required_concepts=[compound_name],
                    alternative_concepts=[],
                    intent="fallback",
                    scope="full_text"
                )]
            )

    async def search_patents(self, queries: List[Any]) -> List[Dict[str, Any]]:
        """Hit the Serper API to get patent links and metadata."""
        logger.info("Executing Serper API normal search for %d queries...", len(queries))
        
        all_results = []
        
        if not self.serper_api_key:
            logger.warning("SERPER_API_KEY is not set. Returning empty list.")
            return []

        # Safe key fingerprint logging
        key_fingerprint = self.serper_api_key[:6] + "..." + self.serper_api_key[-4:] if len(self.serper_api_key) > 10 else "***"
        logger.info("[SERPER CONFIG] Endpoint: https://google.serper.dev/patents | API key configured: true | API key fingerprint: %s", key_fingerprint)

        # Pre-process queries to determine depth
        planned_requests = 0
        high_value = 0
        medium_value = 0
        supporting = 0
        
        query_configs = []
        for q in queries:
            q_str = q.query if hasattr(q, 'query') else q.get('query', q) if isinstance(q, dict) else str(q)
            intent = (q.intent if hasattr(q, 'intent') else q.get('intent', '')) if hasattr(q, 'intent') or isinstance(q, dict) else ''
            scope = (q.scope if hasattr(q, 'scope') else q.get('scope', '')) if hasattr(q, 'scope') or isinstance(q, dict) else ''
            
            intent_lower = intent.lower()
            if "synthesis" in intent_lower or "modification" in intent_lower or "base" in intent_lower or "preparation" in intent_lower or "polymerization" in intent_lower:
                max_pages = 3
                high_value += 1
            elif "process" in intent_lower or "monomer" in intent_lower or "composition" in intent_lower or "feed" in intent_lower or "transformation" in intent_lower:
                max_pages = 2
                medium_value += 1
            else:
                max_pages = 1
                supporting += 1
                
            planned_requests += max_pages
            query_configs.append({"query_str": q_str, "max_pages": max_pages})

        logger.info("[SERPER SEARCH PLAN] Total queries: %d | Maximum requests: %d | High-value queries: %d | Medium-value queries: %d | Supporting queries: %d", 
                    len(queries), planned_requests, high_value, medium_value, supporting)

        async def execute_serper_search(q_configs: List[Dict], endpoint: str, extra_query_modifier: str = "") -> List[Dict[str, Any]]:
            results = []
            seen_pub_nums = set()
            requests_completed = 0
            requests_failed = 0
            requests_avoided = 0
            
            async with httpx.AsyncClient() as client:
                credits_exhausted = False
                for query_idx, qc in enumerate(q_configs, 1):
                    if credits_exhausted:
                        break
                        
                    search_query = f"{extra_query_modifier} {qc['query_str']}".strip()
                    max_p = qc['max_pages']
                    
                    for page in range(1, max_p + 1):
                        payload = {"q": search_query, "page": page}
                        headers = {'X-API-KEY': self.serper_api_key, 'Content-Type': 'application/json'}
                        
                        try:
                            logger.info("[SERPER %s REQUEST] Query %d/%d Page %d/%d: '%s'", endpoint.upper(), query_idx, len(q_configs), page, max_p, search_query)
                            response = await client.post(
                                f"https://google.serper.dev/{endpoint}", 
                                headers=headers, json=payload, timeout=15.0
                            )
                            
                            logger.info(f"[SERPER {endpoint.upper()} RESPONSE] HTTP Status: {response.status_code}")
                            
                            if response.status_code == 400:
                                if "Not enough credits" in response.text:
                                    logger.error("[SERPER QUOTA ERROR] Endpoint: %s | Configured key: %s | Queries planned: %d | Maximum possible requests: %d | Requests completed: %d | Requests failed: %d | Reason: Not enough Serper credits.", 
                                                 endpoint, key_fingerprint, len(q_configs), planned_requests, requests_completed, requests_failed + 1)
                                    raise SerperCreditsExhaustedError("Serper API credits exhausted")
                                else:
                                    logger.error("Serper API 400 Bad Request (Syntax Error). Response: %s", response.text)
                                    requests_failed += 1
                                    break # Skip remaining pages for this malformed query
                                    
                            elif response.status_code in [401, 403]:
                                logger.error("Serper API Auth Error (%d). Response: %s", response.status_code, response.text)
                                raise httpx.HTTPStatusError(f"Serper Auth Error: {response.text}", request=response.request, response=response)
                            elif response.status_code == 429:
                                logger.error("Serper API Rate Limit Error (429). Response: %s", response.text)
                                raise httpx.HTTPStatusError(f"Serper Rate Limit Error: {response.text}", request=response.request, response=response)
                            elif response.status_code >= 500:
                                logger.error("Serper API Upstream Error (%d). Response: %s", response.status_code, response.text)
                                requests_failed += 1
                                break
                            elif response.status_code != 200:
                                logger.error("Serper API non-200. Status: %s, Text: %s", response.status_code, response.text)
                                response.raise_for_status()
                                
                            requests_completed += 1
                            data = response.json()
                            
                            patent_results = data.get("patents", [])
                            if not patent_results and "organic" in data:
                                patent_results = data.get("organic", [])
                                
                            logger.info("[SERPER %s RESPONSE] Extracted %d results for query '%s' on page %d", endpoint.upper(), len(patent_results), search_query, page)
                            
                            if not patent_results:
                                logger.info("No more results for query '%s' on page %d. Stopping pagination.", search_query, page)
                                break
                                
                            new_candidates_on_page = 0
                            for result in patent_results:
                                link = result.get("link", "")
                                pub_num = result.get("publicationNumber")
                                
                                if not pub_num and link:
                                    match = re.search(r'patents\.google\.com/patent/([A-Z0-9]+)', link)
                                    if match:
                                        pub_num = match.group(1)
                                        
                                if not pub_num:
                                    continue
                                    
                                if pub_num in seen_pub_nums:
                                    continue
                                    
                                seen_pub_nums.add(pub_num)
                                new_candidates_on_page += 1
                                
                                results.append({
                                    "patent_number": pub_num,
                                    "title": result.get("title", ""),
                                    "snippet": result.get("snippet", "") or result.get("abstract", ""),
                                    "url": link,
                                    "query_matched": search_query,
                                    "family_id": pub_num,
                                    "publication_date": result.get("publicationDate", ""),
                                    "priority_date": result.get("priorityDate", ""),
                                    "filing_date": result.get("filingDate", ""),
                                    "grant_date": result.get("grantDate", ""),
                                    "inventor": result.get("inventor", ""),
                                    "assignee": result.get("assignee", ""),
                                    "pdf_url": result.get("pdfUrl", ""),
                                    "source": f"serper_{endpoint}"
                                })
                                
                            if new_candidates_on_page == 0:
                                logger.info("Page %d yielded 0 new unique candidates for query '%s'. Early stopping pagination.", page, search_query)
                                requests_avoided += (max_p - page)
                                break
                                
                        except SerperCreditsExhaustedError as e:
                            # If we exhausted credits, we must safely preserve partial discovery.
                            if len(results) > 0:
                                logger.warning("[SERPER PARTIAL DISCOVERY] Credits exhausted midway, but safely preserving %d candidates found so far.", len(results))
                                credits_exhausted = True
                                break # break out of pages loop
                            else:
                                raise e
                        except Exception as e:
                            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in [401, 403, 429]:
                                raise e
                            logger.error("Serper API request failed for query '%s' page %d: %s", search_query, page, e)
                            break
                            
            logger.info("[SERPER SEARCH SUMMARY] Queries attempted: %d | Requests completed: %d | Requests failed: %d | Unique patents: %d | Requests avoided by early stopping: %d", 
                        len(q_configs), requests_completed, requests_failed, len(results), requests_avoided)
            return results

        all_results = await execute_serper_search(query_configs, "patents")
        
        if not all_results:
            logger.warning("[SEARCH] Serper /patents returned ZERO results across all queries. Engaging /search fallback.")
            all_results = await execute_serper_search(query_configs, "search", "site:patents.google.com/patent/")
            
        logger.info("Total discovered Google Patent candidates: %d", len(all_results))
        return all_results

