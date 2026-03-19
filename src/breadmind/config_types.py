"""Extended configuration dataclasses for timeouts, retries, limits, and polling.

Separated from config.py to keep file sizes manageable (SOLID / SRP).
"""

from dataclasses import dataclass


@dataclass
class MemoryGCConfig:
    interval_seconds: int = 3600
    decay_threshold: float = 0.1
    max_cached_notes: int = 500
    kg_max_age_days: int = 90
    env_refresh_interval: int = 6


@dataclass
class TimeoutsConfig:
    tool_call: int = 30
    llm_api: int = 120
    ssh_command: int = 300
    health_check: int = 5
    pypi_check: int = 10
    http_default: int = 10
    skill_discovery: int = 30


@dataclass
class RetryConfig:
    max_retries: int = 3
    llm_max_retries: int = 3
    gateway_max_retries: int = 10
    base_backoff: int = 1
    max_backoff: int = 300
    health_check_interval: int = 30


@dataclass
class LimitsConfig:
    max_tools: int = 30
    max_context_tokens: int = 4000
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
    ollama_base_url: str = "http://localhost:11434"
    cache_size: int = 500

    # Provider default models (read-only reference)
    PROVIDER_DEFAULTS: dict = None  # type: ignore[assignment]

    def __post_init__(self):
        self.PROVIDER_DEFAULTS = {
            "fastembed": {"model": "BAAI/bge-small-en-v1.5", "dimensions": 384},
            "ollama": {"model": "nomic-embed-text", "dimensions": 768},
            "local": {"model": "all-MiniLM-L6-v2", "dimensions": 384},
            "gemini": {"model": "gemini-embedding-001", "dimensions": 768},
            "openai": {"model": "text-embedding-3-small", "dimensions": 1536},
        }


@dataclass
class PollingConfig:
    signal_interval: int = 5
    gmail_interval: int = 30
    update_check_interval: int = 3600
    data_flush_interval: int = 300
    auto_cleanup_interval: int = 600
