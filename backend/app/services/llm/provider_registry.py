"""
app/services/llm/provider_registry.py

Registry of supported LLM providers and logic to instantiate them.
"""
from typing import Dict, Any

import os
from dotenv import dotenv_values

from app.core.config import settings
from app.services.llm.base import BaseLLMProvider
from app.services.llm.gemini_provider import GeminiProvider
from app.services.llm.openai_provider import OpenAIProvider
from app.services.llm.openai_compatible_provider import OpenAICompatibleProvider

# Settings may select only these providers. Others stay implemented for review
# and are not advertised or used as automatic fallbacks.
SELECTABLE_PROVIDER_IDS = ("gemini", "openai")


def fallback_provider_ids(preferred: str, fallback: str | None, enable_fallback: bool) -> list[str]:
    """Primary, then one fallback. Groq and other non-selectable ids are omitted."""
    chain = [preferred]
    if not enable_fallback or not fallback or fallback == preferred:
        return chain
    if fallback in SELECTABLE_PROVIDER_IDS:
        chain.append(fallback)
    return chain


# Provider definitions
# These are the default models and base URLs for the supported providers.
PROVIDER_DEFINITIONS = {
    "gemini": {
        "name": "Gemini",
        "description": "Google Gemini (gemini-2.5-flash)",
        "capabilities": ["Patent Analysis", "Recipe Generation", "Report Generation", "Fast Extraction"],
        "env_key": "GEMINI_API_KEY",
    },
    "openai": {
        "name": "OpenAI",
        "description": "OpenAI (gpt-5.4-mini)",
        "capabilities": ["Patent Analysis", "Recipe Generation", "Report Generation"],
        "env_key": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5.4-mini",
    },
    "grok": {
        "name": "Grok",
        "description": "xAI Grok (grok-beta)",
        "capabilities": ["Patent Analysis", "Recipe Generation", "Report Generation"],
        "env_key": "GROK_API_KEY",
        "base_url": "https://api.x.ai/v1",
        "model": "grok-beta",
    },
    "claude": {
        "name": "Claude",
        "description": "Anthropic Claude (claude-3-5-haiku-latest)",
        "capabilities": ["Patent Analysis", "Recipe Generation", "Report Generation"],
        "env_key": "CLAUDE_API_KEY",
    },
    "deepseek": {
        "name": "DeepSeek",
        "description": "DeepSeek (deepseek-chat)",
        "capabilities": ["Patent Analysis", "Recipe Generation", "Report Generation"],
        "env_key": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "qwen": {
        "name": "Qwen",
        "description": "Alibaba Qwen (qwen-max)",
        "capabilities": ["Patent Analysis", "Recipe Generation", "Report Generation"],
        "env_key": "QWEN_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-max",
    },
    "groq": {
        "name": "Groq",
        "description": "Groq (llama-3.3-70b-versatile)",
        "capabilities": ["Patent Analysis", "Recipe Generation", "Report Generation", "Fast Extraction"],
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
    },
}

def _get_api_key(env_key: str) -> str | None:
    """Dynamically fetches the API key, reading directly from .env to bypass pydantic caching."""
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env")
    env_vals = dotenv_values(env_path)
    return env_vals.get(env_key) or os.environ.get(env_key) or getattr(settings, env_key, None)

def get_provider_status(provider_id: str) -> str:
    """Returns the status of a provider."""
    provider_def = PROVIDER_DEFINITIONS.get(provider_id.lower())
    if not provider_def:
        return "Not Configured"
    
    api_key = _get_api_key(provider_def["env_key"])
    if api_key:
        return "Configured"
    return "API Key Missing"

def instantiate_provider(provider_id: str) -> BaseLLMProvider:
    """Creates a new instance of the requested provider."""
    pid = provider_id.lower()
    
    if get_provider_status(pid) != "Configured":
        raise ValueError(f"Provider '{provider_id}' is not fully configured (Missing API Key).")
        
    pdef = PROVIDER_DEFINITIONS[pid]
    api_key = _get_api_key(pdef["env_key"])
    
    import logging
    logger = logging.getLogger(__name__)
    
    if pid == "gemini":
        logger.info(f"LLM Provider: gemini")
        logger.info(f"Gemini Model: {settings.GEMINI_MODEL if hasattr(settings, 'GEMINI_MODEL') else 'gemini-2.5-flash'}")
        logger.info(f"Gemini API Key: configured")
        return GeminiProvider(api_key=api_key)
        
    if pid == "openai":
        logger.info(f"LLM Provider: openai")
        logger.info(f"LLM Model: {settings.OPENAI_MODEL}")
        logger.info(f"OpenAI API Key: configured")
        return OpenAIProvider(api_key=api_key, model_name=settings.OPENAI_MODEL)
        
    if pid in ["grok", "deepseek", "qwen", "groq"]:
        return OpenAICompatibleProvider(
            api_key=api_key,
            base_url=pdef["base_url"],
            model_name=pdef["model"],
            provider_name=pdef["name"]
        )
        
    if pid == "claude":
        # Anthropic requires the anthropic SDK. 
        # For now, we will raise an error as it needs a specific anthropic_provider.py 
        # but since we don't have the API key anyway, it will be marked "API Key Missing".
        raise NotImplementedError("Native Claude support requires anthropic_provider.py")
        
    raise ValueError(f"Unknown provider: {provider_id}")
