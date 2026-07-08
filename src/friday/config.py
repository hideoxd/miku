"""Central configuration, loaded from environment / a local .env file.

Everything tunable lives here so engines stay swappable and no secret is ever
hard-coded. Fields map to ``FRIDAY_*`` env vars (plus the bare
``OPENROUTER_API_KEY`` and ``HF_HUB_ENABLE_HF_TRANSFER``).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = two levels up from this file (src/friday/config.py -> repo/)
ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="FRIDAY_",
        extra="ignore",
    )

    # ---- Brain (OpenRouter) ---------------------------------------------
    # Note: read from the bare OPENROUTER_API_KEY (no FRIDAY_ prefix) to match
    # the conventional env var name.
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    llm_model: str = "anthropic/claude-haiku-4.5"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    app_url: str = "https://github.com/forloopcodes/friday"
    app_title: str = "FRIDAY"
    llm_temperature: float = 0.6
    max_tool_rounds: int = 6  # safety cap on the tool-call loop

    # ---- Persona / behaviour --------------------------------------------
    assistant_name: str = "FRIDAY"
    wake_word: str = "hey friday"
    log_level: str = "INFO"

    # ---- Miku voice (Phase 2) -------------------------------------------
    miku_space_id: str = ""
    base_voice_lang: str = "ja"  # "en" or "ja" — RVC input voice

    @property
    def has_api_key(self) -> bool:
        return bool(self.openrouter_api_key.strip())


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
