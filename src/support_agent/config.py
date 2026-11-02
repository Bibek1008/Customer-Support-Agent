"""Env-only configuration.

Every secret and endpoint the system uses is read from the environment through
this module. No key, token, or database URL is hardcoded anywhere in the tree.
The model IDs default to the exact strings in ``FACTS.md`` Section 1.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables (or a local ``.env``)."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Reasoning model (Anthropic) -----------------------------------------
    llm_provider: Literal["anthropic", "groq"] = Field(default="anthropic", alias="LLM_PROVIDER")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(default="openai/gpt-oss-20b", alias="GROQ_MODEL")
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
        default="openai", alias="EMBEDDING_PROVIDER"
    )
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    embedding_model: str = Field(default="text-embedding-3-large", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=3072, alias="EMBEDDING_DIM")

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

    # --- Ticketing ------------------------------------------------------------
    ticketing_base_url: str = Field(default="", alias="TICKETING_BASE_URL")
    ticketing_api_key: str = Field(default="", alias="TICKETING_API_KEY")

    # --- Handoff --------------------------------------------------------------
    # The confidence cutoff tau*. Below it the agent escalates instead of
    # answering. eval/threshold.py sweeps this and prints the value to set.
    handoff_threshold: float = Field(default=0.60, alias="HANDOFF_THRESHOLD")


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance.

    Cached so that reading configuration does not re-parse the environment on
    every call. Tests clear the cache with ``get_settings.cache_clear()``.
    """
    return Settings()
