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

    # ---- Voice in (Phase 3) ---------------------------------------------
    input_device: str = ""            # mic device name/index (empty = default)
    mic_sample_rate: int = 16_000
    stt_model: str = "base.en"        # faster-whisper size (tiny.en/base.en/small.en)
    stt_compute_type: str = "int8"    # int8 is the CPU sweet spot
    stt_cpu_threads: int = 4          # pin to the P-cores; 0 = library default
    wake_mode: str = "openwakeword"   # "openwakeword" | "stt" (custom spoken phrase)
    wake_model: str = "hey_jarvis"    # openWakeWord model name or path to a .onnx
    wake_phrase: str = "miku"         # stt mode: word(s) that trigger a wake
    wake_threshold: float = 0.5       # 0-1; higher = fewer false wakes
    vad_threshold: float = 0.5        # silero speech probability threshold
    vad_silence_ms: int = 800         # trailing silence that ends a turn
    bargein_ms: int = 350             # speech-while-speaking that triggers barge-in
    max_utterance_s: float = 15.0     # hard cap on a single spoken turn

    # ---- Miku voice (Phase 2) -------------------------------------------
    # Two backends (both run on HF ZeroGPU -> an HF token is REQUIRED):
    #   "mikutts"   text -> Miku directly via a mikuTTS Space (default, no clip)
    #   "gptsovits" clone Miku from a reference clip via a GPT-SoVITS Space
    miku_backend: str = "mikutts"
    hf_token: str = ""  # FRIDAY_HF_TOKEN (falls back to HF_TOKEN env)

    # -- mikutts backend --
    miku_space_id: str = "John6666/mikuTTS"
    miku_model: str = "HATSUNE MIKU"  # which built-in Miku RVC model
    miku_base_voice: str = "en-US-AriaNeural-Female"  # edge base voice
    miku_f0_up_key: int = 6  # pitch shift toward Miku's register
    miku_index_rate: float = 0.75

    # -- gptsovits backend (reference clone) --
    miku_ref_audio: str = ""   # path to a 3-10s clip of the target voice
    miku_ref_text: str = ""    # transcript of the clip (blank = ref-free mode)
    miku_ref_lang: str = "ja"  # language of the reference clip
    miku_text_lang: str = "en"  # language FRIDAY speaks
    miku_cut: str = "punct"    # how GPT-SoVITS splits: punct|none|4sent|50char

    base_voice_lang: str = "ja"  # "en" or "ja" — base TTS voice hint

    # ---- Skills (Phase 4) -----------------------------------------------
    todoist_token: str = ""   # FRIDAY_TODOIST_TOKEN — enables Todoist skills
    enable_pc_control: bool = True
    enable_web_search: bool = True

    # ---- Background service / tray (Phase 5) ----------------------------
    startup_greeting: bool = False   # speak a short line when the service starts
    tray_notifications: bool = True  # show tray balloon on wake / errors

    # ---- Miku mascot overlay (Phase 6) ----------------------------------
    enable_overlay: bool = True      # show the peeking Miku on wake
    overlay_size: int = 240          # px
    overlay_corner: str = "bottom-right"  # bottom-right | bottom-left

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
