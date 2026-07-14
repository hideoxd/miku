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
        token = settings.resolved_hf_token or None
        backend = (settings.miku_backend or "mikutts").lower()
        if backend == "mikutts":
            from .mikutts_space import MikuTTSSpaceEngine

            return MikuTTSSpaceEngine(
                settings.miku_space_id or "John6666/mikuTTS",
                model=settings.miku_model,
                base_voice=settings.miku_base_voice,
                f0_up_key=settings.miku_f0_up_key,
                index_rate=settings.miku_index_rate,
                hf_token=token,
            )
        if backend == "gptsovits":
            from .gpt_sovits import GptSovitsMikuEngine

            # miku_space_id defaults to the mikutts Space; use the GPT-SoVITS
            # default unless the user pointed it at a GPT-SoVITS Space.
            space = settings.miku_space_id
            if not space or "mikuTTS" in space:
                space = "lj1995/GPT-SoVITS-ProPlus"
            return GptSovitsMikuEngine(
                space,
                settings.miku_ref_audio,
                ref_text=settings.miku_ref_text,
                ref_lang=settings.miku_ref_lang,
                text_lang=settings.miku_text_lang,
                cut=settings.miku_cut,
                speed=settings.tts_speed,
                hf_token=token,
            )
        raise ValueError(f"unknown miku backend: {backend!r}")
    raise ValueError(f"unknown TTS engine: {name!r}")


def _cache_tag(name: str, settings: Settings) -> str:
    """Cache key prefix identifying the *voice*, not just the engine.

    Must include everything that changes the rendered audio — otherwise
    switching (say) the Miku RVC model would replay stale cached phrases.
    """
    if name == "miku":
        backend = (settings.miku_backend or "mikutts").lower()
        if backend == "mikutts":
            voice = (
                f"{settings.miku_model}:{settings.miku_base_voice}:"
                f"{settings.miku_f0_up_key}:{settings.miku_index_rate}"
            )
        else:
            voice = f"{backend}:{settings.miku_ref_audio}"
        return f"{name}:{voice}"
    return f"{name}:{settings.tts_voice}"


class _RuntimeSapiFallback:
    """Wrap a cloud engine so a *synth-time* failure still speaks.

    ``build_tts_engine``'s try/except only covers CONSTRUCTION — an engine that
    connects fine at startup but later throws inside ``synthesize`` (wifi drop,
    ZeroGPU quota, HF 5xx) would otherwise lose the whole reply as silence. This
    catches that and delegates to an offline SAPI voice, built lazily on first
    failure and cached, honouring the module's "always falls back to SAPI"
    promise.
    """

    def __init__(self, inner: TTSEngine, settings: Settings) -> None:
        self.inner = inner
        self._settings = settings
        self._sr = int(getattr(inner, "sample_rate", 22_050))
        self._fallback: TTSEngine | None = None

    @property
    def sample_rate(self) -> int:
        return self._sr

    @property
    def prefers_full_text(self) -> bool:
        return getattr(self.inner, "prefers_full_text", False)

    def synthesize(self, text: str):
        try:
            pcm = self.inner.synthesize(text)
            self._sr = int(self.inner.sample_rate)
            return pcm
        except Exception as exc:  # noqa: BLE001
            log.warning("TTS synth failed (%s); falling back to offline SAPI", exc)
            if self._fallback is None:
                self._fallback = _create("sapi", self._settings)
            pcm = self._fallback.synthesize(text)
            self._sr = int(self._fallback.sample_rate)
            return pcm


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
                    engine, ROOT / "cache" / "tts", tag=_cache_tag(name, settings)
                )
                log.info("phrase caching enabled for '%s'", name)
            # Non-SAPI engines can fail mid-session (network / GPU); wrap them so
            # a synth-time error still falls back to the offline SAPI voice.
            if name != "sapi":
                engine = _RuntimeSapiFallback(engine, settings)
            return engine
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
            log.warning("TTS engine '%s' unavailable: %s", name, exc)

    raise RuntimeError("no TTS engine available — " + "; ".join(errors))
