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
| 1 | Spoken replies (placeholder voice) | `--ptt` |
| 2 | Miku voice | (config flag) |
| 3 | Hands-free wake word + barge-in | `--voice` |
| 4 | Skills: PC control, web, calendar/email/todos | — |

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

FRIDAY clones Miku's voice with **GPT-SoVITS** on a hosted Space — give it a short
reference clip and it speaks any text in that voice. Nothing heavy runs locally.

```bash
pip install gradio_client
```

Then in `.env`:

```ini
FRIDAY_TTS_ENGINE=miku
FRIDAY_MIKU_SPACE_ID=lj1995/GPT-SoVITS-ProPlus
FRIDAY_HF_TOKEN=hf_xxx           # REQUIRED — these Spaces run on ZeroGPU
FRIDAY_MIKU_REF_AUDIO=cache/miku_ref.wav   # a 3-10s clean Miku clip (wav or mp3)
FRIDAY_MIKU_REF_TEXT=            # transcript of the clip (blank = ref-free)
FRIDAY_MIKU_REF_LANG=ja
```

- **HF token:** create a free "read" token at <https://huggingface.co/settings/tokens>.
  Without it, ZeroGPU refuses the request.
- **Reference clip:** 3-10 seconds of clean Miku speech. GPT-SoVITS resamples for
  you, so any wav/mp3 works.

Verify it (writes `cache/tts_selftest.wav`, no OpenRouter key needed):

```bash
python -m friday.main --tts-selftest "Hello, I am Friday." --play
```

If the Miku engine can't start (missing clip/token), FRIDAY automatically falls
back to the offline SAPI voice so it always speaks.

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
