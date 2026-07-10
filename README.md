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
| **4** | Skills: PC control, web, calendar/email/todos | (function-calling tools) |
| **5** | Always-on background service + system tray + auto-start | `--tray` · `--install-autostart` |
| **6** | "Hi Miku" custom wake phrase + peeking Miku desktop mascot | (on by default) |
| **9** | **Living 3D Miku mascot** — articulated, draggable, cursor-tracking | (on by default once set up) |

### "Hi Miku" wake phrase (Phase 6)

`FRIDAY_WAKE_MODE=stt` spots any `FRIDAY_WAKE_PHRASE` (default `miku`) by
transcribing short speech windows — no model training. You can say it in one
breath: *"Hi Miku, what's the weather?"* Set `FRIDAY_WAKE_MODE=openwakeword`
for the cheaper pretrained "Hey Jarvis" detector instead.

### The living 3D Miku mascot (Phase 9)

A real-time **animated 3D Miku** (Tda-style V4X, VRM) lives on your desktop in a
transparent always-on-top window — not an image: a rigged model with articulated
head, arms, torso, fingers, and 60+ facial morphs.

**One-time setup** (~300 MB for Electron, one `npm install`):

```bash
pip install py7zr                        # or: pip install -e .[mascot3d]
python scripts/fetch_miku_vrm.py         # downloads + installs models/miku.vrm
cd mascot3d && npm install               # Electron + three.js + three-vrm, builds the bundle
```

Restart the tray and she's alive. What she does:

- **Idle** — breathes, sways, blinks, twintails swing; glances around when bored.
- **Cursor gaze** — her eyes and head smoothly follow your mouse anywhere on screen
  (eyes lead, head lags — very alive).
- **Wake ("Hi Miku")** — springs up from the bottom with a squash-and-stretch pop,
  **waves at you** with a big smile.
- **Listening** — leans in, eyes wide. **Thinking** — tilts her head, hand to chin.
  **Speaking** — mouth syncs with a talking rhythm, livelier bobs.
- **Drag her** — grab her body and put her anywhere; she dangles surprised while
  carried and remembers the spot across restarts.
- **Headpat** — quick click on her head → blush + happy squint. Try it.
- **Click-through** — everywhere except her body, clicks pass to your desktop.

Config: `FRIDAY_OVERLAY_BACKEND=3d|png|off` (auto-falls back to the Phase-6 PNG
overlay if Electron or the model is missing), `FRIDAY_OVERLAY_SIZE`,
`FRIDAY_OVERLAY_FPS` (default 30), `FRIDAY_OVERLAY_CORNER` (first-run position).
If she ever crashes, the service restarts her automatically (max 3× / 5 min).

Bring your own model: any humanoid `.vrm` works —
`python scripts/fetch_miku_vrm.py --file path\to\model.vrm`.

> **OneDrive tip:** exclude `mascot3d/node_modules` from sync (Settings → Sync →
> choose folders) — thousands of small files sync slowly for zero benefit.

<details>
<summary>Legacy PNG mascot (Phase 6/7/8)</summary>

The old overlay shows a pre-rendered PNG (`assets/miku.png`) in a click-through
Tk window with a jump/pop on wake. It's the automatic fallback
(`FRIDAY_OVERLAY_BACKEND=png`). Re-render the PNG from any `.glb`:
`pip install trimesh "pyglet<2"`, then
`python scripts/render_mascot.py path\to\model.glb --az 25`.
</details>

### Skills (Phase 4)

FRIDAY calls these as tools whenever they help:

- **General chat / Q&A** — just the brain.
- **PC control** — open apps, open websites, get/set volume, media keys, type text.
- **Web search** — keyless via DuckDuckGo (`ddgs`).
- **Productivity** — Todoist (set `FRIDAY_TODOIST_TOKEN`); Google Calendar + Gmail
  (drop an OAuth `credentials.json` in the repo root — see `.env.example`).

Hard-to-reverse actions (sending email) require an explicit confirmation, and the
persona is instructed to confirm verbally before doing anything destructive.

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

## Run 24/7 in the background (system tray + auto-start)

FRIDAY can run hidden in the background with a **system-tray icon**, listening
for the wake word all the time, and start itself at every login.

```bash
pip install pystray pillow pywin32
python -m friday.main --tray               # run hidden now (tray icon appears)
python -m friday.main --install-autostart  # launch hidden at every login
python -m friday.main --autostart-status   # check
python -m friday.main --uninstall-autostart
```

The tray icon's **colour shows state** (teal = idle/listening, amber = thinking,
blue = speaking, grey = paused, red = error). **Right-click** for the menu:

- **Pause / Resume listening** — mutes the mic without quitting (privacy).
- **Open logs**, **Restart**, **Start at login** (toggle), **Quit**.

Auto-start drops a tiny hidden launcher (`FRIDAY.vbs` → `pythonw -m friday.tray`)
into your Startup folder — no console window, no admin, easy to remove. The
service is single-instance and self-healing: a bad turn (network/mic glitch) is
logged and skipped, and the mic stream auto-restarts, so it survives long uptimes.

> On an 8 GB machine it holds ~1–2 GB resident (Whisper + ONNX). Use **Pause** or
> `--uninstall-autostart` to stop it.

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
  models don't license. Don't monetize, publish, or distribute the audio. The 3D
  mascot model is fan-made (Tda-style) — don't redistribute it or use it in VRChat.
- **Privacy:** cloud voice conversion and `edge-tts` send spoken text off your
  machine. For sensitive content, use the fully-local Piper + local-RVC path.
- **Secrets:** this repo lives in a OneDrive-synced folder, so your `.env` (API
  keys) syncs to the cloud with it. Keep the repo out of OneDrive, or exclude it
  from sync, if that bothers you.

## Project layout

```
src/friday/
  main.py            CLI entry (--text / --selftest / --voice / --tray …)
  assistant.py       conversation state + tool loop
  service.py         hands-free VoiceService (wake → STT → LLM → TTS)
  overlay.py         mascot client (3D/PNG backends) + the Tk PNG overlay
  config.py          .env-driven settings
  llm/               OpenRouter engine, streaming, sentence chunker
  skills/            function-calling registry + tools
  stt/ tts/ audio/   swappable engine Protocols
mascot3d/            the 3D mascot (Electron + three.js + three-vrm)
scripts/             fetch_miku_vrm.py · render_mascot.py
tests/               pytest suite (chunker, registry, history, wake, cache)
```

Run the tests: `pip install -e .[dev]` then `pytest`.
