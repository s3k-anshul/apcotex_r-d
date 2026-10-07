"""
app/services/llm/gemini_provider.py

Gemini implementation using google-genai.
"""
import asyncio
import logging
import re
from typing import Type

from google import genai
from google.genai.errors import APIError
from pydantic import ValidationError

from app.core.config import settings
from app.services.llm.base import (
    BaseLLMProvider, T, 
    LLMAuthenticationError, LLMModelUnavailableError,
    LLMRateLimitError, LLMQuotaExhaustedError, 
    LLMProviderUnavailableError, LLMInvalidRequestError,
    LLMInvalidResponseError
)
from app.services.pipeline.schemas import PatentExtraction

logger = logging.getLogger(__name__)

class GeminiProvider(BaseLLMProvider):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.GEMINI_API_KEY

        if self.api_key:
            self.api_key = self.api_key.strip()
        else:
            logger.error("GEMINI_API_KEY_PRESENT: NO")
            raise ValueError("Gemini API key is not configured.")

        self.client = genai.Client(api_key=self.api_key)
        self.model_name = getattr(settings, 'GEMINI_MODEL', None) or "gemini-2.5-flash"
        logger.info("[Gemini] Initialized | model=%s", self.model_name)

    def _classify_quota_error(self, e_str: str) -> tuple[str, float | None]:
        retry_after = None
        match = re.search(r'retry in ([\d\.]+)s', e_str, re.IGNORECASE)
        if match:
            try:
                retry_after = float(match.group(1))
            except ValueError:
                pass
                
        classification = "UNKNOWN_429"
        if "limit: 0" in e_str or "ZERO_QUOTA" in e_str:
            classification = "ZERO_QUOTA"
        elif "GenerateRequestsPerDay" in e_str:
            classification = "RPD_EXCEEDED"
        elif "GenerateRequestsPerMinute" in e_str:
            classification = "RPM_EXCEEDED"
        elif "InputTokensPerModelPerMinute" in e_str or "TokensPer" in e_str:
            classification = "TPM_EXCEEDED"
        
        return classification, retry_after

    def _handle_error(self, e: Exception):
        if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
            logger.error("GEMINI_TIMEOUT: Request timed out: %s", e)
            raise LLMProviderUnavailableError(
                f"Gemini Request Timed Out: {e}",
                provider="gemini",
                model=self.model_name
            ) from e

        if isinstance(e, APIError):
            code = getattr(e, 'code', None)
            e_str = str(e)

            # Explicitly handle API_KEY_INVALID - do not mask as rate limit or other error
            if "API_KEY_INVALID" in e_str or "API key not valid" in e_str:
                logger.error("GEMINI_AUTHENTICATION_FAILED: API_KEY_INVALID")
                raise LLMAuthenticationError(f"Gemini Authentication Failed (API_KEY_INVALID): {e_str}", provider="gemini", model=self.model_name) from e

            if code in (401, 403):
                raise LLMAuthenticationError(f"Gemini Authentication/Permission Error: {e_str}", provider="gemini", model=self.model_name) from e
            elif code == 404 or "model no longer available" in e_str.lower() or "not found" in e_str.lower():
                raise LLMModelUnavailableError(f"Gemini Model Unavailable: {e_str}", provider="gemini", model=self.model_name) from e
            elif code == 400:
                raise LLMInvalidRequestError(f"Gemini Invalid Request: {e_str}", provider="gemini", model=self.model_name) from e
            elif code == 503 or "503" in e_str:
                raise LLMRateLimitError(
                    f"Gemini Service Unavailable (503): {e_str}",
                    provider="gemini",
                    model=self.model_name,
                    retry_after=2.0,
                    quota_type="TEMPORARY_PROVIDER_FAILURE"
                ) from e
            elif code is not None and code >= 500:
                raise LLMProviderUnavailableError(f"Gemini Server Error: {e_str}", provider="gemini", model=self.model_name) from e
            elif code == 429 or "Quota exceeded" in e_str:
                classification, retry_after = self._classify_quota_error(e_str)
                if classification in ["ZERO_QUOTA", "RPD_EXCEEDED"]:
                    raise LLMQuotaExhaustedError(f"Gemini Quota Exhausted ({classification}): {e_str}", provider="gemini", model=self.model_name) from e
                else:
                    raise LLMRateLimitError(
                        f"Gemini Rate Limit ({classification}): {e_str}",
                        provider="gemini",
                        model=self.model_name,
                        retry_after=retry_after,
                        quota_type=classification
                    ) from e

        raise e

    async def generate_text(self, prompt: str, system_prompt: str, temperature: float = 0.2) -> tuple[str, dict]:
        try:
            logger.info("[LLM] Gemini request model: %s", self.model_name)
            config = genai.types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                automatic_function_calling=genai.types.AutomaticFunctionCallingConfig(
                    disable=True,
                    maximum_remote_calls=None,
                ),
            )
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                ),
                timeout=120.0,
            )
            
            usage = {}
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                usage = {
                    "input_tokens": getattr(response.usage_metadata, "prompt_token_count", None),
                    "output_tokens": getattr(response.usage_metadata, "candidates_token_count", None),
                }
                
            return response.text, usage
        except Exception as e:
            self._handle_error(e)

    def _validate_gemini_schema(self, schema: dict, path: str = "root") -> list[str]:
        """
        Recursively validate that all required fields exist in properties.
        Returns list of validation errors.
        """
        errors = []
        
        if not isinstance(schema, dict):
            return errors
            
        # Check if this is an object with properties and required
        if "properties" in schema:
            properties = schema.get("properties", {})
            required = schema.get("required", [])
            
            # Check each required field exists in properties
            for req_field in required:
                if req_field not in properties:
                    errors.append(f"Path: {path} | Required field '{req_field}' not found in properties")
            
            # Recursively validate nested objects in properties
            for prop_name, prop_schema in properties.items():
                nested_path = f"{path}.{prop_name}"
                if isinstance(prop_schema, dict):
                    # Handle array items
                    if "items" in prop_schema and isinstance(prop_schema["items"], dict):
                        errors.extend(self._validate_gemini_schema(prop_schema["items"], f"{nested_path}.items"))
                    # Handle nested objects
                    else:
                        errors.extend(self._validate_gemini_schema(prop_schema, nested_path))
                elif isinstance(prop_schema, list):
                    for idx, item in enumerate(prop_schema):
                        if isinstance(item, dict):
                            errors.extend(self._validate_gemini_schema(item, f"{nested_path}[{idx}]"))
        
        return errors

    async def generate_structured(self, prompt: str, system_prompt: str, schema: Type[T], temperature: float = 0.1) -> tuple[T | None, dict]:
        try:
            from app.services.llm.schema_normalizer import normalize_gemini_schema

            raw_schema = schema.model_json_schema()
            response_schema_dict = normalize_gemini_schema(raw_schema)

            # Validate schema recursively (log errors only)
            validation_errors = self._validate_gemini_schema(response_schema_dict)
            if validation_errors:
                logger.error("[Gemini] Schema validation errors for %s:", schema.__name__)
                for error in validation_errors:
                    logger.error("  %s", error)

            config_kwargs: dict = {
                "system_instruction": system_prompt,
                "response_mime_type": "application/json",
                "response_schema": response_schema_dict,
                "temperature": temperature,
                "automatic_function_calling": genai.types.AutomaticFunctionCallingConfig(
                    disable=True,
                    maximum_remote_calls=None,
                ),
            }
            # Cap report-related output. Unbounded generation produced 340k+ char
            # malformed JSON (run 75f58c61…). With Gemini 3.x, thinking tokens share
            # this budget — too-low caps yield FinishReason.MAX_TOKENS mid-string.
            if schema.__name__ in ("LLMPatentResearchReport", "LLMPatentAnalysis"):
                from app.core.config import settings as _settings
                if schema.__name__ == "LLMPatentAnalysis":
                    max_out = int(
                        getattr(_settings, "REPORT_SECTION_MAX_OUTPUT_TOKENS", 16384) or 16384
                    )
                else:
                    max_out = int(getattr(_settings, "REPORT_MAX_OUTPUT_TOKENS", 65536) or 65536)
                config_kwargs["max_output_tokens"] = max_out
                logger.info(
                    "[Gemini] %s max_output_tokens=%d (thinking tokens included in budget)",
                    schema.__name__,
                    max_out,
                )
            elif schema.__name__ == "LLMOptimizationSet":
                from app.core.config import settings as _settings
                max_out = int(getattr(_settings, "RECIPE_OPTIMIZATION_MAX_OUTPUT_TOKENS", 10240) or 10240)
                config_kwargs["max_output_tokens"] = max_out
                logger.info(
                    "[Gemini] %s max_output_tokens=%d (customer trial optimization budget)",
                    schema.__name__,
                    max_out,
                )
            elif schema.__name__ == "LLMRecipeSet":
                from app.core.config import settings as _settings
                max_out = int(getattr(_settings, "RECIPE_MAX_OUTPUT_TOKENS", 24576) or 24576)
                config_kwargs["max_output_tokens"] = max_out
                logger.info(
                    "[Gemini] %s max_output_tokens=%d (compact recipe generation budget)",
                    schema.__name__,
                    max_out,
                )
            elif schema.__name__ == "LLMCompoundSearchProfile":
                from app.core.config import settings as _settings
                max_out = int(getattr(_settings, "QUERY_EXPANSION_MAX_OUTPUT_TOKENS", 8192) or 8192)
                config_kwargs["max_output_tokens"] = max_out
                logger.info(
                    "[Gemini] %s max_output_tokens=%d (query expansion budget)",
                    schema.__name__,
                    max_out,
                )
            elif schema.__name__ == "PatentSelectionResult":
                from app.core.config import settings as _settings
                max_out = int(getattr(_settings, "PATENT_SELECTION_MAX_OUTPUT_TOKENS", 16384) or 16384)
                config_kwargs["max_output_tokens"] = max_out
                logger.info(
                    "[Gemini] %s max_output_tokens=%d (patent selection budget)",
                    schema.__name__,
                    max_out,
                )

            # Determine finite timeout per schema/stage
            if schema.__name__ == "LLMCompoundSearchProfile":
                from app.core.config import settings as _settings
                timeout_seconds = float(getattr(_settings, "QUERY_EXPANSION_TIMEOUT", 60) or 60)
            elif schema.__name__ in ("LLMPatentResearchReport", "LLMPatentAnalysis"):
                timeout_seconds = 180.0
            else:
                timeout_seconds = 90.0

            config = genai.types.GenerateContentConfig(**config_kwargs)

            logger.info("[LLM] Gemini request model: %s | timeout=%.1fs", self.model_name, timeout_seconds)
            response = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                ),
                timeout=timeout_seconds,
            )

            # Check for EMPTY_RESPONSE before parsing
            if response.text is None:
                logger.error("GEMINI_RESPONSE_ERROR: EMPTY_RESPONSE")
                raise LLMInvalidResponseError("EMPTY_RESPONSE", provider="gemini", model=self.model_name)

            # Diagnostics: finish reason + length (critical for truncation vs malformed)
            finish_reason = None
            try:
                cands = getattr(response, "candidates", None) or []
                if cands:
                    finish_reason = str(getattr(cands[0], "finish_reason", None))
                logger.info("GEMINI_FINISH_REASON: %s", finish_reason)
            except Exception as fr_err:
                logger.debug("Could not read Gemini finish_reason: %s", fr_err)

            logger.info("GEMINI_STRUCTURED_RESPONSE_RECEIVED: YES")
            logger.info("GEMINI_RESPONSE_TYPE: %s", type(response.text))
            logger.info("GEMINI_RESPONSE_LENGTH: %d", len(response.text))
            logger.info("GEMINI_RESPONSE_MIME: application/json")
            if schema.__name__ == "LLMCompoundSearchProfile":
                logger.info(
                    "[QUERY_EXPANSION] Gemini structured response received | length=%d finish_reason=%s",
                    len(response.text),
                    finish_reason,
                )

            usage = {}
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                um = response.usage_metadata
                usage = {
                    "input_tokens": getattr(um, "prompt_token_count", None),
                    "output_tokens": getattr(um, "candidates_token_count", None),
                }
                thoughts = getattr(um, "thoughts_token_count", None)
                if thoughts is not None:
                    usage["thoughts_token_count"] = thoughts
                    logger.info(
                        "GEMINI_THOUGHTS_TOKEN_COUNT: %s | candidates_token_count: %s",
                        thoughts,
                        usage.get("output_tokens"),
                    )
            usage["finish_reason"] = finish_reason
            usage["response_length"] = len(response.text)

            # Try to parse as JSON to get keys
            try:
                import json
                response_dict = json.loads(response.text)
                logger.info("GEMINI_RESPONSE_KEYS: %s", list(response_dict.keys()))
                # Log a sanitized preview (first 200 chars)
                preview = response.text[:200] if len(response.text) > 200 else response.text
                logger.info("GEMINI_RESPONSE_PREVIEW: %s", preview)
            except json.JSONDecodeError as jde:
                logger.warning("GEMINI_RESPONSE_NOT_VALID_JSON")
                # Log context around the failure position for diagnostics
                try:
                    pos = getattr(jde, "pos", None)
                    if pos is not None:
                        start = max(0, int(pos) - 80)
                        end = min(len(response.text), int(pos) + 80)
                        logger.warning(
                            "GEMINI_JSON_ERROR_CONTEXT pos=%s snippet=%r",
                            pos,
                            response.text[start:end],
                        )
                    logger.warning(
                        "GEMINI_JSON_ERROR detail=%s finish_reason=%s response_length=%d",
                        jde,
                        finish_reason,
                        len(response.text),
                    )
                except Exception:
                    pass
                err = LLMInvalidResponseError(
                    f"MALFORMED_JSON: {jde}",
                    provider="gemini",
                    model=self.model_name,
                )
                err.raw_response_text = response.text  # type: ignore[attr-defined]
                err.finish_reason = finish_reason  # type: ignore[attr-defined]
                err._failed_usage = usage  # type: ignore[attr-defined]
                raise err

            usage = {}
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                um = response.usage_metadata
                usage = {
                    "input_tokens": getattr(um, "prompt_token_count", None),
                    "output_tokens": getattr(um, "candidates_token_count", None),
                }
                thoughts = getattr(um, "thoughts_token_count", None)
                if thoughts is not None:
                    usage["thoughts_token_count"] = thoughts
                    logger.info(
                        "GEMINI_THOUGHTS_TOKEN_COUNT: %s | candidates_token_count: %s",
                        thoughts,
                        usage.get("output_tokens"),
                    )
            if finish_reason:
                usage["finish_reason"] = finish_reason
                
            return schema.model_validate_json(response.text), usage

        except ValidationError as ve:
            logger.error("LLM Schema Mode: FAILED. Validation error extracting structured data via Gemini: %s", ve)
            logger.error("Missing or invalid fields in Gemini response. The LLM did not return the expected schema.")
            # Capture whatever usage we can before failing so telemetry records the cost
            _failed_usage = {}
            try:
                if response and hasattr(response, 'usage_metadata') and response.usage_metadata:
                    _failed_usage = {
                        "input_tokens": getattr(response.usage_metadata, "prompt_token_count", None),
                        "output_tokens": getattr(response.usage_metadata, "candidates_token_count", None),
                    }
                elif response and hasattr(response, 'text') and response.text:
                    # Estimate output from response length
                    _failed_usage = {"output_tokens": len(response.text) // 4}
            except Exception:
                pass
            # Attach raw text so callers can salvage partial candidates / drive repair prompts
            try:
                if response is not None and getattr(response, "text", None):
                    ve._raw_response_text = response.text  # type: ignore[attr-defined]
                    ve._failed_usage = _failed_usage  # type: ignore[attr-defined]
            except Exception:
                pass
            raise ve
        except Exception as e:
            self._handle_error(e)

