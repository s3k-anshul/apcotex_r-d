from typing import Any, Dict
import copy
import logging

logger = logging.getLogger(__name__)

def normalize_gemini_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively resolves all $ref references in a Pydantic JSON schema by inlining
    definitions from $defs and removes $defs. This produces a flattened schema
    compatible with Gemini's structured output requirements.

    Also handles anyOf flattening for Optional fields and removes fields Gemini
    doesn't support (additionalProperties, nested required).
    """
    schema_copy = copy.deepcopy(schema)
    defs = schema_copy.pop("$defs", {})

    def _resolve_ref_key(ref_key: str) -> Dict[str, Any]:
        """
        Try to resolve a $ref key that was NOT found in $defs.
        Pydantic v2 may use keys like:
          - "PatentExample"
          - "app__services__pipeline__schemas__PatentExample"
          - "app__services__pipeline__schemas__PatentExample-Input__1"
        We extract the bare class name (after last '__', before '-') and look it up
        in app.services.pipeline.schemas.
        """
        # Strip Pydantic v2 versioning suffix like "-Input__1"
        base_key = ref_key.split("-")[0]
        # Extract class name: last segment after '__'
        class_name = base_key.split("__")[-1]

        try:
            from app.services.pipeline import schemas as _schemas
            cls = getattr(_schemas, class_name, None)
            if cls is None:
                logger.warning("Schema $ref '%s' -> class '%s' not found in schemas module", ref_key, class_name)
                return {}
            cls_schema = cls.model_json_schema()
            if "$defs" in cls_schema:
                defs.update(cls_schema.pop("$defs"))
            resolved = resolve(cls_schema)
            return resolved
        except Exception as e:
            logger.warning("Could not resolve $ref '%s' (class '%s'): %s", ref_key, class_name, e)
            return {}

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_key = node["$ref"].split("/")[-1]
                if ref_key in defs:
                    return resolve(copy.deepcopy(defs[ref_key]))
                else:
                    return _resolve_ref_key(ref_key)

            # Flatten anyOf with a single non-null type (Optional fields)
            if "anyOf" in node:
                non_nulls = [t for t in node["anyOf"] if t.get("type") != "null"]
                if len(non_nulls) == 1:
                    resolved_type = resolve(non_nulls[0])
                    resolved_node = {k: v for k, v in node.items() if k != "anyOf"}
                    resolved_node.update(resolved_type)
                    return resolved_node

            # Recurse into all dict values
            for k, v in node.items():
                node[k] = resolve(v)
            return node

        elif isinstance(node, list):
            return [resolve(item) for item in node]
        else:
            return node

    resolved_schema = resolve(schema_copy)

    def remove_additional_properties(node: Any) -> Any:
        if isinstance(node, dict):
            node.pop("additionalProperties", None)
            for key in list(node.keys()):
                node[key] = remove_additional_properties(node[key])
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                node[idx] = remove_additional_properties(item)
        return node

    resolved_schema = remove_additional_properties(resolved_schema)

    def remove_required_selective(node: Any, path: str = "", inside_report: bool = False) -> Any:
        if isinstance(node, dict):
            properties = node.get("properties", {})

            # Fingerprint the schema type
            has_decision = "decision" in properties
            has_reason = "reason" in properties
            has_compound = "compound" in properties
            has_compound_name = "compound_name" in properties
            has_synonyms = "synonyms" in properties
            has_methodology_patents = "methodology_patents" in properties
            has_cross_comparison = "cross_patent_comparison" in properties
            has_references = "references" in properties
            is_report_root = has_methodology_patents and has_cross_comparison and has_references

            has_patent_details = "patent_details" in properties
            has_experimental_evidence = "experimental_evidence" in properties
            is_report_patent = has_patent_details and has_experimental_evidence

            is_report_type = is_report_root or is_report_patent or inside_report

            if "required" in node:
                if has_decision and has_reason:
                    logger.debug("Preserving required for RankedCandidate at %s", path)
                elif has_compound and has_compound_name and has_synonyms:
                    logger.debug("Preserving required for CompoundSearchProfile at %s", path)
                
                else:
                    del node["required"]

            for key, value in list(node.items()):
                new_path = f"{path}.{key}" if path else key
                node[key] = remove_required_selective(value, new_path, is_report_type)
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                node[idx] = remove_required_selective(item, path, inside_report)
        return node

    resolved_schema = remove_required_selective(resolved_schema)
    return resolved_schema

