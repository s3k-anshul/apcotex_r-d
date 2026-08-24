from app.services.pipeline.search_service import SearchService
from app.models.research_profile import CompoundSearchProfile

def test_strategy():
    service = SearchService()
    profile = CompoundSearchProfile(
        compound_name="Nitrile Butadiene Rubber",
        compound="NBR",
        synonyms=["Nitrile Rubber", "Buna-N"],
        synthesis_terms=["polymerization", "emulsion"],
        transformation_terms=["coagulation", "vulcanization"],
        target_attributes=[],
        search_queries=[]
    )
    queries = service.build_queries(profile)
    print("FINAL QUERIES:")
    for idx, q in enumerate(queries):
        print(f"{idx+1}. {q}")

if __name__ == "__main__":
    test_strategy()
