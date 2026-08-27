import json
from app.services.pipeline.schemas import PatentExtraction
from app.services.llm.schema_normalizer import normalize_gemini_schema

raw = PatentExtraction.model_json_schema(mode='serialization')
print(list(raw.get('$defs', {}).keys()))

try:
    norm = normalize_gemini_schema(raw)
    print("Success")
except Exception as e:
    print(f"Error: {e}")
