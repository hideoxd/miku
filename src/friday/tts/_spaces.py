"""Shared helpers for TTS engines that call hosted gradio Spaces."""

from __future__ import annotations

import inspect


def client_auth_kwargs(client_cls, hf_token: str | None) -> dict:
    """Pass an HF token under whatever keyword this gradio_client version uses."""
    kwargs: dict = {"verbose": False}
    if hf_token:
        params = inspect.signature(client_cls.__init__).parameters
        if "hf_token" in params:
            kwargs["hf_token"] = hf_token
        elif "token" in params:
            kwargs["token"] = hf_token
    return kwargs


def extract_audio_path(result) -> str | None:
    """Pull an audio filepath out of a gradio predict() return value."""
    if isinstance(result, str):
        return result
    if isinstance(result, (list, tuple)):
        for item in result:
            if isinstance(item, str) and item.lower().endswith((".wav", ".mp3", ".flac")):
                return item
        for item in result:
            if isinstance(item, str):
                return item
    if isinstance(result, dict):
        for key in ("path", "name", "value"):
            if isinstance(result.get(key), str):
                return result[key]
    return None
