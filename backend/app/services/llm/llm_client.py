"""
app/services/llm/llm_client.py

Centralized LLM abstraction that dynamically resolves the configured LLM provider from the database.
All services communicate with this singleton.
"""
import logging
import time
import asyncio
import random
from typing import Type, Any
import tiktoken

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.app_config import AppConfig
from app.core.config import settings
from app.services.llm.base import (
    T, 
    LLMAuthenticationError, LLMModelUnavailableError,
    LLMRateLimitError, LLMQuotaExhaustedError, 
    LLMProviderUnavailableError, LLMInvalidRequestError,
    LLMInvalidResponseError
)
from app.services.llm.provider_registry import instantiate_provider, fallback_provider_ids
from app.services.usage_logger import UsageLogger
from app.core.telemetry import get_current_run_id, get_current_stage

logger = logging.getLogger(__name__)

class ProviderExhaustedException(Exception):
    """Raised when all configured LLM providers have been disabled due to fatal errors."""
    pass

class LLMRateLimitException(Exception):
    """Raised when an LLM provider fails due to rate limits after maximum retries."""
    pass


def is_provider_failure(exc: BaseException) -> bool:
    """True only for outages that may use the configured fallback provider.

    Schema failures, invalid requests, and context/token-limit request errors
    stay on the selected provider. Quota, authentication, model availability,
    and provider outages may fall back.
    """
    return isinstance(
        exc,
        (
            LLMAuthenticationError,
            LLMModelUnavailableError,
            LLMQuotaExhaustedError,
            LLMProviderUnavailableError,
        ),
    )


class DynamicLLMClient:
    def __init__(self):
        self.disabled_providers = set()
        self.provider_health = {}
        self.semaphore = asyncio.Semaphore(3) # Centralized rate limiting
        self._selected_provider: str | None = None
        self._fallback_from: str | None = None
        self._fallback_reason: str | None = None

    def reset_health(self):
        self.disabled_providers.clear()
        self.provider_health.clear()
        self._selected_provider = None
        self._fallback_from = None
        self._fallback_reason = None
        logger.info("[LLM] Provider health state reset for new run.")

    def _note_fallback(self, provider_id: str, reason: str) -> None:
        self.disabled_providers.add(provider_id)
        self._fallback_from = provider_id
        self._fallback_reason = reason
        logger.warning("[LLM] FALLBACK | from=%s reason=%s", provider_id, reason)

    def _usage_metadata(self, provider_id: str, model_name: str | None, extra: dict | None = None) -> dict:
        meta = {
            "selected_provider": self._selected_provider or provider_id,
            "actual_provider": provider_id,
            "model": model_name,
        }
        if self._fallback_reason:
            meta["fallback_from"] = self._fallback_from
            meta["fallback_reason"] = self._fallback_reason
        if extra:
            meta.update(extra)
        cost = (extra or {}).get("estimated_cost")
        if cost is None and extra:
            cost = extra.get("cost")
        if cost is not None:
            meta["estimated_cost"] = cost
        return meta

    async def _get_available_provider(self) -> tuple[str, Any]:
        """Fetches the first available configured LLM provider, avoiding disabled ones."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(AppConfig).where(AppConfig.key == "active_llm_provider"))
            config = result.scalar_one_or_none()

            preferred_provider = settings.PRIMARY_LLM
            if config and isinstance(config.value, dict) and "provider_id" in config.value:
                preferred_provider = config.value["provider_id"]
            self._selected_provider = preferred_provider

            fallback_order = fallback_provider_ids(
                preferred_provider,
                settings.FALLBACK_LLM,
                settings.ENABLE_FALLBACK,
            )

            for provider_id in fallback_order:
                if provider_id in self.disabled_providers:
                    logger.debug("[LLM] Skipping disabled provider: %s", provider_id)
                    if provider_id == preferred_provider and not self._fallback_reason:
                        self._fallback_from = provider_id
                        self._fallback_reason = "provider_unavailable"
                    continue
                try:
                    provider = instantiate_provider(provider_id)
                    logger.debug("[LLM] Selected provider: %s", provider_id)
                    return provider_id, provider
                except ValueError as ve:
                    if "Missing API Key" in str(ve) or "not configured" in str(ve):
                        logger.debug("[LLM] %s disabled: API key not configured", provider_id)
                        reason = "provider_unavailable"
                    else:
                        logger.warning("[LLM] Failed to instantiate '%s': %s", provider_id, type(ve).__name__)
                        reason = "provider_unavailable"
                    self._note_fallback(provider_id, reason)
                except Exception as e:
                    logger.warning("[LLM] Failed to instantiate '%s': %s", provider_id, type(e).__name__)
                    self._note_fallback(provider_id, "provider_unavailable")

            raise ProviderExhaustedException(
                f"All configured LLM providers exhausted. Primary was: {preferred_provider}. "
                f"Disabled: {self.disabled_providers}"
            )

    async def generate_text(self, prompt: str, system_prompt: str, temperature: float = 0.2) -> str:
        import uuid
        logical_call_id = str(uuid.uuid4())
        provider_id, provider = await self._get_available_provider()
        
        # Calculate token estimate
        try:
            encoder = tiktoken.get_encoding("cl100k_base")
            token_count = len(encoder.encode(prompt + system_prompt))
        except Exception:
            token_count = len(prompt) // 4
            
        start_time = time.time()
        model_name = getattr(provider, 'model_name', 'UNKNOWN')
        
        logger.info("=" * 60)
        logger.info(f"LLM REQUEST INITIATED: UNKNOWN ({model_name}) | Tokens: {token_count} (est)")
        logger.info("=" * 60)
        max_retries = 2
        base_delay = 2.0
        
        for attempt in range(max_retries + 1):
            try:
                async with self.semaphore:
                    result, usage = await provider.generate_text(prompt, system_prompt, temperature)
                duration = time.time() - start_time
                in_tokens = usage.get("input_tokens") or token_count
                out_tokens = usage.get("output_tokens") or 0
                tot_tokens = in_tokens + out_tokens
                
                run_id = get_current_run_id() or "UNKNOWN"
                stage = getattr(get_current_stage(), 'value', None) or "UNKNOWN"
                
                logger.info("LLM REQUEST")
                logger.info("-" * 11)
                logger.info(f"Run ID: {run_id}")
                logger.info(f"Stage: {stage}")
                logger.info(f"Provider: {provider_id.upper()}")
                logger.info(f"Model: {model_name}")
                logger.info(f"Request Type: TEXT")
                logger.info(f"Attempt: {attempt + 1}")
                logger.info(f"Input Tokens: {in_tokens}")
                logger.info(f"Output Tokens: {out_tokens}")
                logger.info(f"Total Tokens: {tot_tokens}")
                logger.info(f"Estimated Cost: N/A")
                logger.info(f"Latency: {duration:.2f}s")
                logger.info(f"Status: SUCCESS")
                logger.info(f"Error Type: NONE")
                logger.info("=" * 60)
                # Log success
                await UsageLogger.record_api_usage(
                    provider=provider_id,
                    operation="generate_text",
                    model=getattr(provider, 'model_name', None),
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    latency_ms=int(duration * 1000),
                    status="success",
                    retry_count=attempt,
                    metadata=self._usage_metadata(
                        provider_id,
                        model_name,
                        {
                            "logical_call_id": logical_call_id,
                            "estimated_cost": usage.get("estimated_cost", usage.get("cost")),
                        },
                    ),
                )
                
                return result
            except Exception as e:
                if isinstance(e, LLMModelUnavailableError):
                    logger.error("[LLM] Model unavailable for %s: %s", provider_id, type(e).__name__)
                    self._note_fallback(provider_id, "model_unavailable")
                    return await self.generate_text(prompt, system_prompt, temperature)
                elif isinstance(e, LLMQuotaExhaustedError):
                    logger.info("=" * 60)
                    logger.info("LLM DAILY QUOTA EXHAUSTED")
                    logger.info("-" * 25)
                    logger.info(f"Provider: {provider_id.upper()}")
                    logger.info(f"Requested Tokens: {token_count} (est)")
                    logger.info(f"Status: FAILED")
                    logger.info("=" * 60)
                    duration = time.time() - start_time
                    self._note_fallback(provider_id, "quota_exhausted")
                    await UsageLogger.record_api_usage(
                        provider=provider_id,
                        operation="generate_text",
                        model=getattr(provider, 'model_name', None),
                        input_tokens=token_count,
                        latency_ms=int(duration * 1000),
                        status="failed",
                        error_type=type(e).__name__,
                        error_message=type(e).__name__,
                        retry_count=attempt,
                        metadata=self._usage_metadata(provider_id, model_name, {"logical_call_id": logical_call_id}),
                    )
                    return await self.generate_text(prompt, system_prompt, temperature)
                elif isinstance(e, LLMRateLimitError):
                    if attempt < max_retries:
                        delay = getattr(e, "retry_after", None) or (base_delay * (2 ** attempt) + random.uniform(0, 1))
                        logger.warning("[LLM] %s rate limit (%s). Retrying in %.2f sec (Attempt %d/%d)", provider_id, getattr(e, "quota_type", "UNKNOWN_429"), delay, attempt+1, max_retries)
                        await asyncio.sleep(delay)
                    else:
                        logger.error("[LLM] Max retries reached for %s rate limit. Failing gracefully.", provider_id)
                        
                        run_id = get_current_run_id() or "UNKNOWN"
                        stage = getattr(get_current_stage(), 'value', None) or "UNKNOWN"
                        
                        logger.info("LLM REQUEST")
                        logger.info("-" * 11)
                        logger.info(f"Run ID: {run_id}")
                        logger.info(f"Stage: {stage}")
                        logger.info(f"Provider: {provider_id.upper()}")
                        logger.info(f"Model: {model_name}")
                        logger.info(f"Request Type: TEXT")
                        logger.info(f"Attempt: {attempt + 1}")
                        logger.info(f"Input Tokens: {token_count} (est)")
                        logger.info(f"Output Tokens: 0")
                        logger.info(f"Total Tokens: {token_count}")
                        logger.info(f"Estimated Cost: N/A")
                        logger.info(f"Latency: {time.time() - start_time:.2f}s")
                        logger.info(f"Status: FAILED")
                        logger.info(f"Error Type: RATE_LIMITED")
                        logger.info("=" * 60)
                        self._note_fallback(provider_id, "rate_limited")
                        return await self.generate_text(prompt, system_prompt, temperature)
                elif isinstance(e, LLMAuthenticationError):
                    logger.error("[LLM] Authentication failed for %s", provider_id)
                    self._note_fallback(provider_id, "authentication_failed")
                    return await self.generate_text(prompt, system_prompt, temperature)
                elif isinstance(e, LLMProviderUnavailableError):
                    logger.error("[LLM] Provider unavailable: %s", provider_id)
                    self._note_fallback(provider_id, "provider_unavailable")
                    return await self.generate_text(prompt, system_prompt, temperature)
                elif isinstance(e, LLMInvalidRequestError):
                    logger.error("[LLM] Invalid request sent to %s", provider_id)
                    raise e # Context, token, or schema request errors do not fall back
                else:
                    logger.error("[LLM] Unexpected error from %s: %s", provider_id, type(e).__name__)
                    duration = time.time() - start_time
                    await UsageLogger.record_api_usage(
                        provider=provider_id,
                        operation="generate_text",
                        model=getattr(provider, 'model_name', None),
                        input_tokens=token_count, # Estimated
                        latency_ms=int(duration * 1000),
                        status="failed",
                        error_type=type(e).__name__,
                        error_message=type(e).__name__,
                        retry_count=attempt,
                        metadata=self._usage_metadata(provider_id, model_name, {"logical_call_id": logical_call_id}),
                    )
                    raise
                    
        raise LLMRateLimitError("Rate limited.")

    async def generate_structured(self, prompt: str, system_prompt: str, schema: Type[T], temperature: float = 0.1, metadata: dict | None = None) -> tuple[T | None, str, dict]:
        import uuid
        logical_call_id = str(uuid.uuid4())
        provider_id, provider = await self._get_available_provider()
        metadata = metadata or {}

        try:
            encoder = tiktoken.get_encoding("cl100k_base")
            token_count = len(encoder.encode(prompt + system_prompt))
        except Exception:
            token_count = len(prompt) // 4

        start_time = time.time()
        model_name = getattr(provider, 'model_name', 'UNKNOWN')
        stage_val = metadata.get('stage') or getattr(get_current_stage(), 'value', None) or "UNKNOWN"
        schema_name = schema.__name__ if schema else 'UNKNOWN'

        logger.info("[LLM] %s | %s | %s | ~%d tokens", stage_val, provider_id, schema_name, token_count)

        max_retries = 5   # 503/429 can need 30-90s to clear; 5 retries with exponential backoff
        base_delay = 10.0  # 10s → 20s → 40s → 80s → 160s

        for attempt in range(max_retries + 1):
            try:
                async with self.semaphore:
                    result, usage = await provider.generate_structured(prompt, system_prompt, schema, temperature)
                duration = time.time() - start_time
                in_tokens = usage.get("input_tokens") or token_count
                out_tokens = usage.get("output_tokens") or 0

                logger.info(
                    "[LLM] OK | %s | %s | in=%d out=%d lat=%.1fs",
                    stage_val, provider_id, in_tokens, out_tokens, duration
                )

                await UsageLogger.record_api_usage(
                    provider=provider_id,
                    operation="generate_structured",
                    model=model_name,
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    latency_ms=int(duration * 1000),
                    status="success",
                    retry_count=attempt,
                    metadata=self._usage_metadata(
                        provider_id,
                        model_name,
                        {
                            "schema_name": schema_name,
                            "logical_call_id": logical_call_id,
                            "estimated_cost": usage.get("estimated_cost", usage.get("cost")),
                        },
                    ),
                )
                return result, provider_id, usage

            except Exception as e:
                from pydantic import ValidationError as PydanticValidationError
                duration = time.time() - start_time

                if isinstance(e, PydanticValidationError):
                    failed_usage = getattr(e, '_failed_usage', {}) or {}
                    raw_text = getattr(e, '_raw_response_text', None)
                    if raw_text:
                        failed_usage = {**failed_usage, "raw_response_text": raw_text}
                    failed_usage["validation_error"] = str(e)[:2000]
                    logger.warning(
                        "[LLM] VALIDATION_FAILED | %s | %s | schema=%s | lat=%.1fs",
                        stage_val, provider_id, schema_name, duration
                    )
                    await UsageLogger.record_api_usage(
                        provider=provider_id, operation="generate_structured", model=model_name,
                        input_tokens=failed_usage.get("input_tokens") or token_count,
                        output_tokens=failed_usage.get("output_tokens") or 0,
                        latency_ms=int(duration * 1000), status="validation_failed",
                        error_type="ValidationError", error_message=str(e)[:500],
                        retry_count=attempt, metadata={"schema_name": schema_name, "logical_call_id": logical_call_id}
                    )
                    # Validation error is a per-request failure — do NOT disable provider
                    return None, provider_id, failed_usage

                elif isinstance(e, LLMInvalidResponseError):
                    # Malformed/empty response is a per-request content error.
                    # Do NOT disable the provider — the next patent should still be able to use it.
                    raw_text = getattr(e, "raw_response_text", None)
                    finish_reason = getattr(e, "finish_reason", None)
                    err_usage = getattr(e, "_failed_usage", {}) or {}
                    failed_usage = {
                        **err_usage,
                        "invalid_response_error": str(e)[:2000],
                        "finish_reason": finish_reason,
                        "is_truncated": getattr(e, "is_truncated", False) or err_usage.get("is_truncated", False),
                        "response_length": len(raw_text) if raw_text else 0,
                    }
                    if raw_text:
                        failed_usage["raw_response_text"] = raw_text
                    logger.warning(
                        "[LLM] INVALID_RESPONSE | %s | %s | %s | lat=%.1fs | "
                        "finish_reason=%s response_length=%d — provider kept enabled",
                        stage_val, provider_id, str(e)[:120], duration,
                        finish_reason, failed_usage["response_length"],
                    )
                    await UsageLogger.record_api_usage(
                        provider=provider_id, operation="generate_structured", model=model_name,
                        input_tokens=failed_usage.get("input_tokens") or token_count,
                        output_tokens=failed_usage.get("output_tokens") or 0,
                        latency_ms=int(duration * 1000),
                        status="failed", error_type="LLMInvalidResponseError",
                        error_message=type(e).__name__, retry_count=attempt,
                        metadata=self._usage_metadata(
                            provider_id, model_name, {"schema_name": schema_name, "logical_call_id": logical_call_id}
                        )
                    )
                    return None, provider_id, failed_usage

                elif isinstance(e, LLMModelUnavailableError):
                    logger.error("[LLM] MODEL_UNAVAILABLE | %s", provider_id)
                    self._note_fallback(provider_id, "model_unavailable")
                    return await self.generate_structured(prompt, system_prompt, schema, temperature, metadata)

                elif isinstance(e, LLMQuotaExhaustedError):
                    logger.error(
                        "[LLM] QUOTA_EXHAUSTED | %s | ~%d tokens | disabling provider",
                        provider_id, token_count
                    )
                    self._note_fallback(provider_id, "quota_exhausted")
                    await UsageLogger.record_api_usage(
                        provider=provider_id, operation="generate_structured", model=model_name,
                        input_tokens=token_count, latency_ms=int(duration * 1000),
                        status="failed", error_type=type(e).__name__, error_message=type(e).__name__,
                        retry_count=attempt,
                        metadata=self._usage_metadata(
                            provider_id, model_name, {"schema_name": schema_name, "logical_call_id": logical_call_id}
                        ),
                    )
                    return await self.generate_structured(prompt, system_prompt, schema, temperature, metadata)

                elif isinstance(e, LLMRateLimitError):
                    if attempt < max_retries:
                        delay = getattr(e, "retry_after", None) or (base_delay * (2 ** attempt) + random.uniform(0, 1))
                        logger.warning(
                            "[LLM] RATE_LIMITED | %s | quota_type=%s | retry in %.1fs (%d/%d)",
                            provider_id, getattr(e, 'quota_type', 'UNKNOWN'), delay, attempt + 1, max_retries
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error("[LLM] RATE_LIMITED | %s | max retries reached", provider_id)
                        self._note_fallback(provider_id, "rate_limited")
                        return await self.generate_structured(prompt, system_prompt, schema, temperature, metadata)

                elif isinstance(e, LLMAuthenticationError):
                    logger.error("[LLM] AUTH_FAILED | %s", provider_id)
                    self._note_fallback(provider_id, "authentication_failed")
                    return await self.generate_structured(prompt, system_prompt, schema, temperature, metadata)

                elif isinstance(e, LLMProviderUnavailableError):
                    logger.error("[LLM] PROVIDER_UNAVAILABLE | %s", provider_id)
                    self._note_fallback(provider_id, "provider_unavailable")
                    return await self.generate_structured(prompt, system_prompt, schema, temperature, metadata)

                elif isinstance(e, LLMInvalidRequestError):
                    logger.error("[LLM] INVALID_REQUEST | %s | %s", provider_id, type(e).__name__)
                    # Context limits and malformed requests stay on this provider.
                    raise e

                else:
                    # Generic/unexpected error — do NOT disable provider for extraction calls.
                    # Log and return None so this single patent fails but others can continue.
                    logger.error(
                        "[LLM] UNEXPECTED_ERROR | %s | %s | %s | lat=%.1fs",
                        stage_val, provider_id, type(e).__name__, duration
                    )
                    await UsageLogger.record_api_usage(
                        provider=provider_id, operation="generate_structured", model=model_name,
                        input_tokens=token_count, latency_ms=int(duration * 1000),
                        status="failed", error_type=type(e).__name__, error_message=str(e)[:300],
                        retry_count=attempt, metadata={"schema_name": schema_name, "logical_call_id": logical_call_id}
                    )
                    return None, provider_id, {}

        raise LLMRateLimitError("Rate limited.")

# Singleton instance for easy importing
llm_client = DynamicLLMClient()
