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

## The Miku voice spike

Before wiring Miku in, benchmark the cloud path:

```bash
pip install gradio_client
python scripts/spike_rvc_benchmark.py --space <your-hf-user>/mikuTTS
```

Measures warm round-trip latency and lets you compare an English vs Japanese base
voice. See the spike output to decide cloud-vs-local and base-voice language.

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
