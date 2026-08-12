"""Centralized, import-safe application settings for bac-genius.

Values are loaded from environment variables and/or a local ``.env`` file
(see ``.env.example`` for the full list of supported keys). The module
exposes a lazily-constructed singleton via :func:`get_settings` so that
importing this module never fails (and never performs I/O) even if no
``.env`` file is present -- every field has a safe default.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["openai", "gemini", "ollama"]


class Settings(BaseSettings):
    """Application-wide configuration.

    All fields can be overridden via environment variables of the same
    name, or via a ``.env`` file in the project root.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- LLM provider selection -------------------------------------------------
    LLM_PROVIDER: LLMProvider = "gemini"

    # --- Provider credentials ----------------------------------------------------
    OPENAI_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None

    # --- Local / self-hosted LLM (Ollama) -----------------------------------------
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:7b-instruct"

    # --- Vector store & cache -----------------------------------------------------
    QDRANT_URL: str = "http://localhost:6333"
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Embeddings ----------------------------------------------------------------
    EMBEDDING_MODEL: str = "intfloat/multilingual-e5-large"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton.

    ``lru_cache`` guarantees the environment/``.env`` file is only parsed
    once per process, and that every caller receives the same instance.
    """

    return Settings()


# Convenience singleton for `from config.settings import settings`.
settings: Settings = get_settings()
