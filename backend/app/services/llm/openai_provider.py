"""
app/services/llm/openai_provider.py

OpenAI implementation using the official openai SDK.
Supports structured outputs via Pydantic parsing.
"""
import asyncio
import logging
from typing import Type

from openai import AsyncOpenAI, RateLimitError, APIConnectionError, APIError, AuthenticationError
from pydantic import ValidationError

from app.core.config import settings
from app.services.llm.base import BaseLLMProvider, T, LLMRateLimitError

logger = logging.getLogger(__name__)

class OpenAIProvider(BaseLLMProvider):
    def __init__(self, api_key: str | None = None, model_name: str | None = None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        if not self.api_key:
            raise ValueError("OpenAI API key is not configured.")
        
        self.client = AsyncOpenAI(api_key=self.api_key)
        self.model_name = model_name or settings.OPENAI_MODEL or "gpt-5.4-mini"

    def _handle_error(self, e: Exception):
        if isinstance(e, AuthenticationError):
            raise ValueError(f"OpenAI Authentication Error: {e}")
        elif isinstance(e, RateLimitError):
            raise LLMRateLimitError(f"OpenAI Rate Limit Exceeded: {e}")
        elif isinstance(e, APIConnectionError):
            raise ConnectionError(f"OpenAI Connection Error: {e}")
        elif isinstance(e, APIError):
            raise RuntimeError(f"OpenAI API Error: {e}")
        raise e

    async def generate_text(self, prompt: str, system_prompt: str, temperature: float = 0.2) -> str:
        retries = 2
        delay = 2
        
        for attempt in range(retries + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=temperature,
                )
                usage = {}
                if hasattr(response, 'usage') and response.usage:
                    usage = {
                        "input_tokens": getattr(response.usage, "prompt_tokens", None),
                        "output_tokens": getattr(response.usage, "completion_tokens", None),
                    }
                return response.choices[0].message.content, usage
            except Exception as e:
                try:
                    self._handle_error(e)
                except LLMRateLimitError as rle:
                    logger.warning("[LLM] OpenAI rate limit detected: %s", rle)
                    raise rle
                except Exception as ex:
                    if attempt < retries:
                        logger.warning("[LLM] OpenAI error (Attempt %d): %s. Retrying in %.1f sec...", attempt+1, ex, delay)
                        await asyncio.sleep(delay)
                        delay *= 2
                    else:
                        raise ex

    async def generate_structured(self, prompt: str, system_prompt: str, schema: Type[T], temperature: float = 0.1) -> tuple[T | None, dict]:
        retries = 2
        delay = 2
        
        for attempt in range(retries + 1):
            try:
                # Use beta.chat.completions.parse for guaranteed structured outputs mapping to Pydantic
                response = await self.client.beta.chat.completions.parse(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=temperature,
                    response_format=schema
                )
                
                usage = {}
                if hasattr(response, 'usage') and response.usage:
                    usage = {
                        "input_tokens": getattr(response.usage, "prompt_tokens", None),
                        "output_tokens": getattr(response.usage, "completion_tokens", None),
                    }
                
                return response.choices[0].message.parsed, usage
                
            except ValidationError as ve:
                logger.error("LLM Schema Mode: FAILED. Validation error extracting structured data via OpenAI: %s", ve)
                return None, {}
            except Exception as e:
                import openai
                try:
                    self._handle_error(e)
                except LLMRateLimitError as rle:
                    logger.warning("[LLM] OpenAI rate limit detected: %s", rle)
                    raise rle
                except Exception as ex:
                    if isinstance(ex, openai.BadRequestError):
                        logger.error("[LLM] OpenAI 400 Bad Request detected (Schema likely invalid): %s", ex)
                        raise ex
                    if attempt < retries:
                        logger.warning("[LLM] OpenAI error (Attempt %d): %s. Retrying in %.1f sec...", attempt+1, ex, delay)
                        await asyncio.sleep(delay)
                        delay *= 2
                    else:
                        logger.error("LLM Structured Extraction failed via OpenAI due to persistent errors.")
                        return None, {}
