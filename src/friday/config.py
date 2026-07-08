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
    llm_max_tokens: int = 800  # spoken replies are short; also caps cost/credits
    max_tool_rounds: int = 6  # safety cap on the tool-call loop

    # ---- Persona / behaviour --------------------------------------------
    assistant_name: str = "FRIDAY"
    wake_word: str = "hey friday"
    log_level: str = "INFO"

    # ---- Voice out (Phase 1) --------------------------------------------
    tts_engine: str = "sapi"  # sapi | edge | piper | kokoro
    tts_voice: str = ""       # engine-specific voice id / model path (empty = default)
    tts_speed: float = 1.0    # 1.0 = normal
    output_device: str = ""   # sounddevice device name or index (empty = system default)
    tts_min_chars: int = 25   # sentence-chunk threshold before speaking
    tts_cache: bool = True    # cache rendered phrases (helps slow engines like Miku)

    # ---- Miku voice (Phase 2) -------------------------------------------
    # GPT-SoVITS Space that clones a voice from a reference clip. These run on
    # HF ZeroGPU, so an HF token is REQUIRED to allocate the GPU.
    miku_space_id: str = "lj1995/GPT-SoVITS-ProPlus"
    miku_ref_audio: str = ""   # path to a 3-10s clip of the target (Miku) voice
    miku_ref_text: str = ""    # transcript of the clip (blank = ref-free mode)
    miku_ref_lang: str = "ja"  # language of the reference clip
    miku_text_lang: str = "en"  # language FRIDAY speaks
    miku_cut: str = "punct"    # how GPT-SoVITS splits: punct|none|4sent|50char
    hf_token: str = ""         # FRIDAY_HF_TOKEN (falls back to HF_TOKEN env)
    base_voice_lang: str = "ja"  # "en" or "ja" — base TTS voice hint

    @property
    def resolved_hf_token(self) -> str:
        import os

        return self.hf_token.strip() or os.environ.get("HF_TOKEN", "").strip()

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
