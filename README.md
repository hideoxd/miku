# FRIDAY 🎙️

A personal, Tony-Stark-style voice assistant that **thinks via [OpenRouter](https://openrouter.ai)**
and **speaks with Hatsune Miku's voice**. Say *"Hey Friday"*, ask something, and Miku answers.

> Personal, non-commercial project. See **Legal & privacy** below.

## Architecture — thin local edge + cloud brain

Tuned for a CPU-only laptop (no NVIDIA GPU, 8 GB RAM):

```
"Hey Friday"        speech            text             streamed reply        sentence
  (openWakeWord) → capture → VAD → faster-whisper → OpenRouter LLM → chunker → Kokoro/Piper TTS
                                                                                     │
                                              Miku voice (RVC v2, cloud GPU) ◄───────┘ → 🔊 playback
```

Wake-word, VAD, STT and base TTS run locally; the LLM runs in OpenRouter; the one
heavy step — **Miku voice conversion** — is offloaded to a free cloud GPU. Every
stage is behind a `Protocol`, so engines are swappable.

## Build phases

| Phase | What works | Run |
|---|---|---|
| **0** | Text chat + tool-calling brain | `python -m friday.main --text` |
| **1** | Spoken replies | `--text --speak` |
| **2** | Miku voice | `FRIDAY_TTS_ENGINE=miku` |
| **3** | Push-to-talk / hands-free wake word + barge-in | `--ptt` · `--voice` |
| 4 | Skills: PC control, web, calendar/email/todos | (function-calling tools) |

### Voice input (Phase 3)

```bash
pip install faster-whisper openwakeword silero-vad scipy
python -m friday.main --ptt      # press Enter, speak, hear Miku reply
python -m friday.main --voice    # say "Hey Jarvis", then speak (barge-in supported)
```

STT is faster-whisper `base.en` (int8, CPU); endpointing/barge-in use Silero-VAD;
wake word is openWakeWord (default `hey_jarvis` — a custom "hey friday" needs a
model trained via openWakeWord's notebook, then set `FRIDAY_WAKE_MODEL`).
**Use headphones** so the mic doesn't hear Miku.

## Quick start (Phase 0)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e .                    # or: pip install -r requirements.txt
copy .env.example .env              # then add your OPENROUTER_API_KEY

python -m friday.main --selftest    # offline: verify tools + chunker (no key)
python -m friday.main --text        # chat (needs the key)
```

Try: *"what time is it?"* and *"set a 10 second timer called tea"*.

## Configuration

All settings live in `.env` (see `.env.example`). Key ones:

- `OPENROUTER_API_KEY` — from <https://openrouter.ai/keys>
- `FRIDAY_LLM_MODEL` — any tool-capable model, e.g. `anthropic/claude-haiku-4.5`,
  `openai/gpt-4o-mini`, `google/gemini-2.0-flash`
- `FRIDAY_MIKU_SPACE_ID` — your duplicated Miku RVC Space (Phase 2)

## Enabling the Miku voice (Phase 2)

FRIDAY speaks with Hatsune Miku's voice via a hosted **mikuTTS** Space
(`edge-tts` → RVC). It's **text → Miku directly — no reference clip needed**.

```bash
pip install gradio_client
```

Then in `.env`:

```ini
FRIDAY_TTS_ENGINE=miku
FRIDAY_HF_TOKEN=hf_xxx          # REQUIRED — the Space runs on HF ZeroGPU
FRIDAY_MIKU_BACKEND=mikutts     # default
FRIDAY_MIKU_SPACE_ID=John6666/mikuTTS
FRIDAY_MIKU_MODEL=HATSUNE MIKU  # or MikuAI, "Hatsune Miku V2 - VOCALOID (RVC) 250 Epoch", …
FRIDAY_MIKU_BASE_VOICE=en-US-AriaNeural-Female
FRIDAY_MIKU_F0_UP_KEY=6         # raise if Miku sounds too low
```

- **HF token (required):** create a free "read" token at
  <https://huggingface.co/settings/tokens>. Without it, ZeroGPU refuses the call.
- **Latency:** ~15–30 s per reply on the free shared GPU (the whole reply is sent
  in one call; repeated fixed lines are cached and instant). For snappier Miku,
  duplicate the Space onto dedicated hardware.

Verify (writes `cache/tts_selftest.wav`; add `--play` to hear it; no OpenRouter key needed):

```bash
python -m friday.main --tts-selftest "Hello, I am Friday." --play
```

**Alternative backend** — clone Miku from your own reference clip via GPT-SoVITS:
set `FRIDAY_MIKU_BACKEND=gptsovits`, `FRIDAY_MIKU_SPACE_ID=lj1995/GPT-SoVITS-ProPlus`,
and `FRIDAY_MIKU_REF_AUDIO=<a 3-10s clip>`.

If the Miku engine can't start (missing token, Space down), FRIDAY automatically
falls back to the offline SAPI voice so it always speaks.

## Legal & privacy

- **Personal, non-commercial only.** Hatsune Miku is Crypton Future Media's
  character (Piapro Character License); her voice is a separate right that fan RVC
  models don't license. Don't monetize, publish, or distribute the audio.
- **Privacy:** cloud voice conversion and `edge-tts` send spoken text off your
  machine. For sensitive content, use the fully-local Piper + local-RVC path.

## Project layout

```
src/friday/
  main.py            CLI entry (--text / --selftest)
  assistant.py       conversation state + tool loop
  config.py          .env-driven settings
  llm/               OpenRouter engine, streaming, sentence chunker
  skills/            function-calling registry + tools
  stt/ tts/ audio/   engine Protocols (filled in Phases 1-3)
scripts/             spike_rvc_benchmark.py
```
