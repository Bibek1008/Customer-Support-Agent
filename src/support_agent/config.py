"""Env-only configuration.

Every secret and endpoint the system uses is read from the environment through
this module. No key, token, or database URL is hardcoded anywhere in the tree.
The model IDs default to the exact strings in ``FACTS.md`` Section 1.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables (or a local ``.env``)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = Field(
        default="development", alias="APP_ENV"
    )
    persistence_enabled: bool = Field(default=False, alias="PERSISTENCE_ENABLED")
    app_origin: str = Field(default="http://127.0.0.1:8001", alias="APP_ORIGIN")
    render_external_url: str = Field(default="", alias="RENDER_EXTERNAL_URL")
    admin_api_key: str = Field(default="", alias="ADMIN_API_KEY")
    service_api_key: str = Field(default="", alias="SERVICE_API_KEY")
    session_days: int = Field(default=7, alias="SESSION_DAYS", ge=1, le=30)
    history_messages: int = Field(default=20, alias="HISTORY_MESSAGES", ge=2, le=100)
    rate_limit_per_minute: int = Field(default=20, alias="RATE_LIMIT_PER_MINUTE", ge=1, le=1000)
    database_pool_size: int = Field(default=10, alias="DATABASE_POOL_SIZE", ge=2, le=50)
    inference_concurrency: int = Field(default=2, alias="INFERENCE_CONCURRENCY", ge=1, le=8)
    allow_fixture_orders: bool = Field(default=True, alias="ALLOW_FIXTURE_ORDERS")
    business_mode: Literal["demo", "live"] = Field(default="demo", alias="BUSINESS_MODE")
    answer_mode: Literal["extractive", "generated"] = Field(
        default="extractive", alias="ANSWER_MODE"
    )
    business_name: str = Field(
        default="Demo Office Store", alias="BUSINESS_NAME", min_length=1, max_length=100
    )
    safety_provider: Literal["disabled", "server", "groq"] = Field(
        default="server", alias="SAFETY_PROVIDER"
    )
    safety_groq_model: str = Field(
        default="openai/gpt-oss-safeguard-20b", alias="SAFETY_GROQ_MODEL"
    )

    pricing_requires_review: bool = Field(default=True, alias="PRICING_REQUIRES_REVIEW")

    def validate_production(self) -> None:
        if self.app_env != "production":
            return
        missing = []
        if not self.persistence_enabled:
            missing.append("PERSISTENCE_ENABLED=1")
        if not self.app_origin.startswith("https://"):
            missing.append("HTTPS APP_ORIGIN")
        if len(self.admin_api_key) < 32 or len(self.service_api_key) < 32:
            missing.append("separate ADMIN_API_KEY and SERVICE_API_KEY (32+ characters)")
        if self.admin_api_key == self.service_api_key:
            missing.append("distinct staff and service credentials")
        if self.llm_provider != "groq" or self.groq_model != "openai/gpt-oss-20b":
            missing.append("LLM_PROVIDER=groq and the configured Groq model")
        if (
            self.embedding_provider != "fastembed"
            or self.embedding_model != "BAAI/bge-small-en-v1.5"
            or self.embedding_dim != 384
        ):
            missing.append("local FastEmbed BAAI/bge-small-en-v1.5 at 384 dimensions")
        if self.gemini_fallback_enabled:
            missing.append("GEMINI_FALLBACK_ENABLED=0 for zero-cost operation")
        if self.database_pool_size > 2 or self.inference_concurrency > 1:
            missing.append(
                "DATABASE_POOL_SIZE<=2 and INFERENCE_CONCURRENCY=1 for the free instance"
            )
        if self.ticketing_base_url:
            missing.append("TICKETING_BASE_URL empty to use the built-in staff inbox")
        if self.safety_provider == "disabled" or (
            self.safety_provider == "server" and not self.safety_model_url
        ):
            missing.append("configured safety classifier")
        if self.safety_provider == "groq" and not self.groq_api_key:
            missing.append("GROQ_API_KEY for safety")
        if self.gemini_fallback_enabled and not self.gemini_api_key:
            missing.append("GEMINI_API_KEY for enabled fallback")
        if self.allow_fixture_orders and self.business_mode != "demo":
            missing.append("ALLOW_FIXTURE_ORDERS=0")
        if missing:
            raise RuntimeError("Production configuration requires: " + "; ".join(missing))

    # --- Reasoning model (Anthropic) -----------------------------------------
    llm_provider: Literal["anthropic", "groq"] = Field(default="groq", alias="LLM_PROVIDER")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(default="openai/gpt-oss-20b", alias="GROQ_MODEL")
    gemini_fallback_enabled: bool = Field(default=False, alias="GEMINI_FALLBACK_ENABLED")
    gemini_fallback_model: Literal["gemini-3.5-flash-lite"] = Field(
        default="gemini-3.5-flash-lite", alias="GEMINI_FALLBACK_MODEL"
    )
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    agent_model: str = Field(default="claude-opus-4-8", alias="AGENT_MODEL")
    router_model: str = Field(default="claude-sonnet-5", alias="ROUTER_MODEL")
    classifier_model: str = Field(default="claude-haiku-4-5", alias="CLASSIFIER_MODEL")
    # Depth control for the reasoner. FACTS.md: budget_tokens/temperature are
    # rejected on Opus 4.8 / Sonnet 5; depth is set with output_config.effort.
    agent_effort: Literal["low", "medium", "high", "xhigh", "max"] = Field(
        default="high", alias="AGENT_EFFORT"
    )
    # Hard ceiling on output tokens per assistant turn. Streaming is used for
    # any large value to avoid HTTP timeouts.
    max_output_tokens: int = Field(default=8000, alias="MAX_OUTPUT_TOKENS")
    max_agent_steps: int = Field(default=8, alias="MAX_AGENT_STEPS")

    # --- Storage --------------------------------------------------------------
    database_url: str = Field(
        default="postgresql://support:support@localhost:5432/support",
        alias="DATABASE_URL",
    )

    kb_docs_path: str = Field(default="knowledge_base/approved", alias="KB_DOCS_PATH")
    kb_chunk_size: int = Field(default=900, alias="KB_CHUNK_SIZE", gt=0)
    kb_chunk_overlap: int = Field(default=150, alias="KB_CHUNK_OVERLAP", ge=0)
    heldout_dataset_path: str = Field(
        default="eval/datasets/heldout_tickets.jsonl",
        alias="SUPPORT_HELDOUT_DATASET_PATH",
    )

    # --- Embeddings -----------------------------------------------------------
    embedding_provider: Literal["openai", "bge-m3", "fastembed", "gemini"] = Field(
        default="fastembed", alias="EMBEDDING_PROVIDER"
    )
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=384, alias="EMBEDDING_DIM")

    # --- Self-hosted safety classifier (Llama Guard 4) ------------------------
    hugging_face_hub_token: str = Field(default="", alias="HUGGING_FACE_HUB_TOKEN")
    safety_model_url: str = Field(default="", alias="SAFETY_MODEL_URL")
    safety_model_name: str = Field(
        default="meta-llama/Llama-Guard-4-12B", alias="SAFETY_MODEL_NAME"
    )

    # --- Tracing --------------------------------------------------------------
    langfuse_public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    langfuse_base_url: str = Field(default="", alias="LANGFUSE_BASE_URL")
    langfuse_environment: str = Field(default="development", alias="LANGFUSE_TRACING_ENVIRONMENT")
    otel_endpoint: str = Field(default="", alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    otel_service_name: str = Field(default="support-agent", alias="OTEL_SERVICE_NAME")
    tracing_enabled: bool = Field(default=True, alias="TRACING_ENABLED")
    langfuse_sample_rate: float = Field(default=1.0, alias="LANGFUSE_SAMPLE_RATE", ge=0, le=1)
    langfuse_monthly_trace_budget: int = Field(
        default=1000, alias="LANGFUSE_MONTHLY_TRACE_BUDGET", ge=0
    )

    # --- Ticketing ------------------------------------------------------------
    ticketing_base_url: str = Field(default="", alias="TICKETING_BASE_URL")
    ticketing_api_key: str = Field(default="", alias="TICKETING_API_KEY")

    # --- Handoff --------------------------------------------------------------
    # The confidence cutoff tau*. Below it the agent escalates instead of
    # answering. eval/threshold.py sweeps this and prints the value to set.
    handoff_threshold: float = Field(default=0.60, alias="HANDOFF_THRESHOLD", ge=0, le=1)

    @model_validator(mode="after")
    def use_render_origin(self):
        if (
            self.app_env == "production"
            and not self.app_origin.startswith("https://")
            and self.render_external_url.startswith("https://")
        ):
            self.app_origin = self.render_external_url.rstrip("/")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance.

    Cached so that reading configuration does not re-parse the environment on
    every call. Tests clear the cache with ``get_settings.cache_clear()``.
    """
    return Settings()
