"""Text-to-speech engines (Phase 1) + Miku voice conversion (Phase 2).

``build_tts_engine`` picks the configured engine and always falls back to the
offline SAPI voice so FRIDAY can still speak if an optional engine or its deps
are missing.
"""

from __future__ import annotations

import logging

from ..config import ROOT, Settings
from .base import TTSEngine

log = logging.getLogger("friday.tts")

__all__ = ["TTSEngine", "build_tts_engine"]

# Engines slow enough to benefit from phrase caching (network / GPU round-trips).
_CACHEABLE = {"edge", "piper", "kokoro", "miku"}


def _create(name: str, settings: Settings) -> TTSEngine:
    name = name.lower()
    if name == "sapi":
        from .sapi_tts import SapiEngine

        return SapiEngine(voice=settings.tts_voice, speed=settings.tts_speed)
    if name == "edge":
        from .edge_tts import EdgeEngine

        return EdgeEngine(
            voice=settings.tts_voice, speed=settings.tts_speed, lang=settings.base_voice_lang
        )
    if name == "piper":
        from .piper_tts import PiperEngine

        return PiperEngine(model_path=settings.tts_voice, speed=settings.tts_speed)
    if name == "miku":
        from .gpt_sovits import GptSovitsMikuEngine

        return GptSovitsMikuEngine(
            settings.miku_space_id,
            settings.miku_ref_audio,
            ref_text=settings.miku_ref_text,
            ref_lang=settings.miku_ref_lang,
            text_lang=settings.miku_text_lang,
            cut=settings.miku_cut,
            speed=settings.tts_speed,
            hf_token=settings.resolved_hf_token or None,
        )
    raise ValueError(f"unknown TTS engine: {name!r}")


def build_tts_engine(settings: Settings) -> TTSEngine:
    """Build the requested engine, falling back to SAPI on any failure."""
    requested = (settings.tts_engine or "sapi").lower()
    order = [requested] + (["sapi"] if requested != "sapi" else [])

    errors: list[str] = []
    for name in order:
        try:
            engine = _create(name, settings)
            if name != requested:
                log.warning("using fallback TTS engine '%s' (requested '%s')", name, requested)
            else:
                log.info("TTS engine: %s (%d Hz)", name, engine.sample_rate)
            if settings.tts_cache and name in _CACHEABLE:
                from .caching import CachingTTS

                engine = CachingTTS(
                    engine, ROOT / "cache" / "tts", tag=f"{name}:{settings.tts_voice}"
                )
                log.info("phrase caching enabled for '%s'", name)
            return engine
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            log.warning("TTS engine '%s' unavailable: %s", name, exc)

    raise RuntimeError("no TTS engine available — " + "; ".join(errors))
