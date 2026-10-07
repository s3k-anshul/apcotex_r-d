import asyncio
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.services.llm.llm_client import DynamicLLMClient
from app.schemas.recipe import LLMRecipeSet
from app.services.prompts.patent_prompts import RECIPE_GENERATION_SYSTEM_PROMPT
from app.services.recipe_service import (
    _normalize_recipe_stages,
    validate_and_enrich_water_based_recipe,
    calculate_recipe_confidence_score,
    RecipeService,
)

async def test_live_sbr_generation():
    print("Testing live SBR generation with Gemini...")
    llm = DynamicLLMClient()

    target_compound = "Styrene-Butadiene Rubber (SBR)"
    target_properties_text = (
        "ACTIVE TARGET CONSTRAINTS:\n"
        "- Mooney Viscosity: 45 to 55 MU\n"
        "- Bound Styrene: 23 to 25 wt%\n"
        "- Glass Transition (Tg): -55 to -50 °C"
    )
    competitor_text = "No competitor product benchmarks provided (reference only)."
    patent_context_text = (
        "REPORT-DERIVED SYNTHESIS OPTIONS:\n"
        "- Monomer options/ranges: 1,3-Butadiene: 70-75 phr; Styrene: 25-30 phr\n"
        "- Initiator/catalyst options: p-Menthane hydroperoxide / FeSO4 redox system; Potassium persulfate\n"
        "- Emulsifier/surfactant options: Disproportionated rosin acid soap; Potassium oleate\n"
        "- Chain transfer agent (CTA) options: tert-Dodecyl mercaptan (t-DDM): 0.15-0.25 phr\n"
        "- Temperature ranges: 5-10 °C (Cold emulsion polymerization)\n"
        "- Reaction time / feeding ranges: 8-10 hours polymerization time\n"
        "- Additional synthesis parameters: DEHA / SDDC shortstop agent; Vacuum steam stripping\n\n"
        "PATENT SUPPORT (BY PATENT):\n"
        "- US20250075019A1: Cold emulsion polymerization | Values: 1,3-Butadiene: 72 phr; Styrene: 28 phr; Potassium soap: 2.5 phr\n"
        "- US9876543B2: Redox emulsion polymerization | Values: t-DDM: 0.20 phr; DEHA shortstop: 0.15 phr"
    )

    patent_context_dict = {
        "patents": [
            {
                "patent": "US20250075019A1",
                "synthesis_method": "Cold emulsion polymerization",
                "disclosed_parameters": ["1,3-Butadiene", "Styrene", "Potassium soap"],
            },
            {
                "patent": "US9876543B2",
                "synthesis_method": "Redox emulsion polymerization",
                "disclosed_parameters": ["t-DDM", "DEHA shortstop"],
            },
        ]
    }

    prompt = RECIPE_GENERATION_SYSTEM_PROMPT.format(
        compound_name=target_compound,
        target_properties=target_properties_text,
        competitor_data=competitor_text,
        patent_context=patent_context_text,
    )

    user_msg = (
        f"Generate EXACTLY 5 candidate recipes for {target_compound} using a strictly WATER-BASED synthesis route. "
        "Each candidate must vary a different synthesis dimension. "
        "Monomers and ingredients must be dynamically derived for the target compound. "
        "Ensure complete synthesis stages (water medium, emulsifier/surfactant handling, initiator, monomer mix, shortstop/stripping). "
        "Return ONLY valid JSON matching LLMRecipeSet."
    )

    parsed_data, raw_text, usage = await llm.generate_structured(
        prompt=user_msg,
        system_prompt=prompt,
        schema=LLMRecipeSet,
        temperature=0.2,
    )

    print(f"Generated {len(parsed_data.recipes)} recipes. Raw output token approx chars: {len(raw_text)}")

    service = RecipeService(session=None)
    for idx, r in enumerate(parsed_data.recipes):
        r_dict = _normalize_recipe_stages(r.model_dump(), target_compound=target_compound)
        verified_patents = service._verify_patent_references(r_dict, patent_context_dict)
        r_dict["patent_references"] = verified_patents
        r_dict = validate_and_enrich_water_based_recipe(
            recipe=r_dict,
            target_compound=target_compound,
            patent_context=patent_context_dict,
        )
        score = calculate_recipe_confidence_score(
            recipe=r_dict,
            target_properties=[
                {"feature": "Mooney Viscosity", "min": "45", "max": "55", "unit": "MU"},
                {"feature": "Bound Styrene", "min": "23", "max": "25", "unit": "%"},
                {"feature": "Tg", "min": "-55", "max": "-50", "unit": "°C"},
            ],
            competitor_data=[],
            patent_context=patent_context_dict,
        )
        r_dict["confidence_score"] = score

        print(f"\n--- Candidate {idx + 1}: {r_dict.get('name')} ---")
        print(f"Method: {r_dict.get('polymerization_method')}")
        print(f"Confidence Score: {score}")
        print(f"Patent References: {verified_patents}")
        print(f"Stages:")
        for stg in r_dict.get("stages", []):
            p_names = [f"{p.get('name')}: {p.get('value')} {p.get('unit')} ({p.get('source')})" for p in stg.get("parameters", [])]
            if stg.get("is_applicable") is False:
                print(f"  - {stg.get('stage_name')}: Not Applicable | Reason: {stg.get('omission_reason')}")
            else:
                print(f"  - {stg.get('stage_name')} ({len(stg.get('parameters', []))} items): {', '.join(p_names[:3])}")

        # Assertions
        assert "solution" not in r_dict.get("polymerization_method", "").lower() or "aqueous" in r_dict.get("polymerization_method", "").lower()
        # Verify emulsifier solution bug is not present
        stage_names = [s.get("stage_name") for s in r_dict.get("stages", [])]
        for s in r_dict.get("stages", []):
            if s.get("stage_name") == "Emulsifier Solution" and s.get("is_applicable") is False:
                assert "charged directly" not in str(s.get("omission_reason", "")).lower()
        assert score >= 50
        assert len(verified_patents) >= 1

    print("\nALL SBR LIVE GENERATION CHECKS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(test_live_sbr_generation())
