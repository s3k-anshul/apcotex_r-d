"""
app/core/config.py

Centralised application settings using Pydantic-Settings.
All values are loaded from environment variables or a .env file.
"""
from functools import lru_cache
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # ── App ──────────────────────────────────────────────────────────────────
    DEBUG: bool = False
    
    # ── Patent Pipeline ──────────────────────────────────────────────────────
    PRIMARY_PATENT_TARGET: int = 15
    TARGET_PATENTS: int = 15
    MIN_REQUIRED_PATENTS: int = 15
    MAX_FINAL_PATENTS: int = 15
    # When exactly one competitor assignee is supplied, workflow B may keep
    # this many qualifying patents (1 or 2). Multiple assignees stay at one each.
    ASSIGNEE_MAX_PATENTS_WHEN_SINGLE: int = 1
    # Company-name lookup pages per autocomplete query. Each page is one Serper request.
    ASSIGNEE_SUGGESTION_MAX_PAGES: int = 3
    # Full bibliographic checks per assignee when a snippet is not enough.
    ASSIGNEE_DOCUMENT_CHECKS: int = 3
    MAX_SEARCH_RESULTS: int = 10
    MAX_SEARCH_PAGES_PER_QUERY: int = 3
    TOP_LLM_CANDIDATES: int = 15
    MAX_PATENT_DOWNLOADS: int = 15
    SEARCH_CACHE_TTL_DAYS: int = 30
    SEARCH_CACHE_VERSION: int = 1
    BYPASS_SEARCH_CACHE: bool = False
    
    # ── Budgets & Circuit Breakers ──
    MAX_EXTRACTION_INPUT_TOKENS: int = 50000
    PROVIDER_SAFE_LIMIT: int = 9000            # Per-call limit for extraction LLM calls
    # Report generation limits
    # The report LLM (Gemini/GPT-4o) supports up to 100K+ input tokens.
    # We use 100K as a safe working limit; evidence budget 88K leaves ~12K for
    # system prompt + schema + patent manifest + safety margin.
    REPORT_PROVIDER_SAFE_LIMIT: int = 100000   # Max total report prompt (provider input limit)
    REPORT_SAFE_EVIDENCE_BUDGET: int = 88000   # Max evidence tokens (excl. overhead)
    REPORT_EVIDENCE_OVERHEAD_TOKENS: int = 4000  # Reserved for sys prompt + template + manifest
    # Cap Gemini report output to prevent runaway unterminated-string dumps (~340k chars).
    # Gemini 3.x thinking tokens COUNT against max_output_tokens — 8k was too low and
    # caused FinishReason.MAX_TOKENS mid-JSON (truncated/unterminated strings). Model max is 65k.
    REPORT_MAX_OUTPUT_TOKENS: int = 65536
    # Per-patent sectional fallback (when single-shot report still hits MAX_TOKENS).
    REPORT_SECTION_MAX_OUTPUT_TOKENS: int = 16384
    # Recipe Simulator output token budget. Target response size is <= 3000 tokens for 5 compact recipes;
    # 16384 provides a safe upper bound accommodating Gemini 2.5/3.x thinking tokens (~2.5k-4k) alongside
    # the structured response while preventing truncation and avoiding runaway 65k token generation.
    RECIPE_MAX_OUTPUT_TOKENS: int = 24576
    # Query expansion output token budget (Gemini 3.5 thinking tokens + profile schema)
    # 8192 prevents unbounded runaway loops producing infinite repeating characters.
    QUERY_EXPANSION_MAX_OUTPUT_TOKENS: int = 8192
    QUERY_EXPANSION_TIMEOUT: int = 60
    PATENT_SELECTION_MAX_OUTPUT_TOKENS: int = 16384
    # Hard token limit for a single patent extraction LLM call (no longer used but kept for compat)
    MAX_EXTRACTION_LLM_TOKENS: int = 8000
    # How many deterministic params to include in the slim initial_json sent to LLM
    MAX_EXTRACTION_DET_PARAMS_IN_PROMPT: int = 20
    GLOBAL_TOKEN_BUDGET: int = 100000

    # Defaults apply only when the environment and database do not set a provider.
    # Gemini is the primary; OpenAI is the fallback. Groq stays implemented but is
    # not part of the default fallback chain.
    PRIMARY_LLM: str = "gemini"
    FALLBACK_LLM: str = "openai"
    ENABLE_FALLBACK: bool = True
    # Development accounts are created only when this is explicitly enabled.
    SEED_DEFAULT_USERS: bool = False
    MAX_EXTRACTION_CALLS: int = 15
    MAX_TOTAL_LLM_CALLS: int = 20

    # 🤖 LLM Settings 🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖🤖
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ── Database ────────────────────────────────────────────────────────────
    DATABASE_URL: str

    # ── AI API Keys (placeholders for Phase 2) ───────────────────────────────
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.5-flash"
    SERPER_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-5.4-mini"
    GROK_API_KEY: str = ""
    CLAUDE_API_KEY: str = ""
    DEEPSEEK_API_KEY: str = ""
    QWEN_API_KEY: str = ""
    GROQ_API_KEY: str = ""

    # ── Logging ──────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"

    # ── App ──────────────────────────────────────────────────────────────────
    APP_NAME: str = "Apcotex R&D API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_must_be_set(cls, v: str) -> str:
        if not v or v == "your-super-secret-key-change-in-production-min-32-chars":
            raise ValueError("SECRET_KEY must be set to a strong random value.")
        return v

    @model_validator(mode="after")
    def validate_llm_keys(self):
        # We now validate API keys at runtime via provider_registry.py
        # when a specific provider is requested.
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()


settings: Settings = get_settings()
