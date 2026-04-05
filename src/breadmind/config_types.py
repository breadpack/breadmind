"""Extended configuration dataclasses for timeouts, retries, limits, and polling.

Separated from config.py to keep file sizes manageable (SOLID / SRP).
"""

from dataclasses import dataclass

from breadmind.constants import (
    DEFAULT_BASE_BACKOFF,
    DEFAULT_GC_INTERVAL,
    DEFAULT_GATEWAY_MAX_RETRIES,
    DEFAULT_KG_MAX_AGE_DAYS,
    DEFAULT_LLM_TIMEOUT,
    DEFAULT_MAX_BACKOFF,
    DEFAULT_MAX_CACHED_NOTES,
    DEFAULT_MAX_CONTEXT_TOKENS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MAX_TOOLS,
    DEFAULT_OLLAMA_URL,
    DEFAULT_SSH_TIMEOUT,
    DEFAULT_TOOL_TIMEOUT,
    EMBEDDING_FASTEMBED_MODEL,
    EMBEDDING_GEMINI_MODEL,
    EMBEDDING_LOCAL_MODEL,
    EMBEDDING_OLLAMA_MODEL,
    EMBEDDING_OPENAI_MODEL,
)


@dataclass
class MemoryGCConfig:
    interval_seconds: int = DEFAULT_GC_INTERVAL
    decay_threshold: float = 0.1
    max_cached_notes: int = DEFAULT_MAX_CACHED_NOTES
    kg_max_age_days: int = DEFAULT_KG_MAX_AGE_DAYS
    env_refresh_interval: int = 6


@dataclass
class TimeoutsConfig:
    tool_call: int = DEFAULT_TOOL_TIMEOUT
    llm_api: int = DEFAULT_LLM_TIMEOUT
    ssh_command: int = DEFAULT_SSH_TIMEOUT
    health_check: int = 5
    pypi_check: int = 10
    http_default: int = 10
    skill_discovery: int = 30


@dataclass
class RetryConfig:
    max_retries: int = DEFAULT_MAX_RETRIES
    llm_max_retries: int = DEFAULT_MAX_RETRIES
    gateway_max_retries: int = DEFAULT_GATEWAY_MAX_RETRIES
    base_backoff: int = DEFAULT_BASE_BACKOFF
    max_backoff: int = DEFAULT_MAX_BACKOFF
    health_check_interval: int = 30


@dataclass
class LimitsConfig:
    max_tools: int = DEFAULT_MAX_TOOLS
    max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS
    max_per_domain_skills: int = 1
    audit_log_recent: int = 50
    embedding_cache_size: int = 500
    low_performance_threshold: float = 0.5
    top_roles_limit: int = 5
    smart_retriever_token_budget: int = 2000
    smart_retriever_limit: int = 5


@dataclass
class EmbeddingConfig:
    provider: str = "auto"  # "fastembed", "ollama", "local", "gemini", "openai", "auto", "off"
    model_name: str = ""  # empty = use provider default
    ollama_base_url: str = DEFAULT_OLLAMA_URL
    cache_size: int = 500

    # Provider default models (read-only reference)
    PROVIDER_DEFAULTS: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        self.PROVIDER_DEFAULTS = {
            "fastembed": {"model": EMBEDDING_FASTEMBED_MODEL, "dimensions": 384},
            "ollama": {"model": EMBEDDING_OLLAMA_MODEL, "dimensions": 768},
            "local": {"model": EMBEDDING_LOCAL_MODEL, "dimensions": 384},
            "gemini": {"model": EMBEDDING_GEMINI_MODEL, "dimensions": 768},
            "openai": {"model": EMBEDDING_OPENAI_MODEL, "dimensions": 1536},
        }


@dataclass
class PollingConfig:
    signal_interval: int = 5
    gmail_interval: int = 30
    update_check_interval: int = 3600
    data_flush_interval: int = 300
    auto_cleanup_interval: int = 600
