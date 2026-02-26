# Transit Cabin Agent — Project Brief

## Overview

Voice-first LLM agent for a small autonomous public transit vehicle. The only user input is audio (microphone). Output channels are speech (TTS), a 1080×360 display (browser-based), and mock vehicle API calls controlling lights, climate, and audio.

The agent is proactive — it uses ride context to offer help at key moments rather than waiting for users to discover capabilities. Tone is calm, brief, co-pilot — not a smart speaker.

---

## Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | asyncio throughout |
| LLM | Claude API (`claude-sonnet-4-6`) | Tool use for vehicle control |
| STT | `faster-whisper` | Local Whisper inference |
| VAD | `silero-vad` via `torch` | Continuous mic monitoring |
| TTS | ElevenLabs API | `pyttsx3` as offline fallback |
| Display | Electron / Chromium fullscreen | 1080×360, WebSocket-driven |
| Mock Vehicle API | FastAPI on `localhost:8001` | Simulates cabin hardware |

---

## Project Structure

```
transit-agent/
├── agent/
│   ├── main.py            # asyncio entrypoint
│   ├── audio_input.py     # VAD + Whisper STT pipeline
│   ├── audio_output.py    # TTS playback
│   ├── llm.py             # Claude client, tool definitions, conversation loop
│   ├── proactive.py       # Contextual trigger system
│   └── context.py         # Ride state model
├── vehicle_api/
│   ├── server.py          # FastAPI mock server
│   └── state.py           # In-memory cabin state
├── display/
│   ├── index.html         # 1080×360 UI
│   ├── main.js            # Electron entry
│   └── ws_client.js       # WebSocket client
├── config.py              # API keys, device settings, feature flags
├── .env.example
└── README.md
```

---

## Environment Variables

```env
ANTHROPIC_API_KEY=
ELEVENLABS_API_KEY=
ELEVENLABS_VOICE_ID=
WHISPER_MODEL=base.en
VEHICLE_API_PORT=8001
WS_PORT=8765
```

---

## Module Specs

### `vehicle_api/server.py` — Mock Vehicle API

FastAPI server on `localhost:8001`. All state is in-memory. Log every change to console.

**Endpoints:**

| Method | Path | Body |
|---|---|---|
| GET | `/state` | — |
| POST | `/lights` | `{ brightness: int, color_temp: str }` |
| POST | `/climate` | `{ temp_f: int, fan_speed: str }` |
| POST | `/audio` | `{ action: str, genre: str \| null }` |

---

### `agent/context.py` — Ride State Model

Holds all runtime context injected into the LLM on every turn. For prototyping, values are injectable via CLI flags or a mock config.

```python
@dataclass
class RideContext:
    route_name: str
    current_stop: str
    next_stop: str
    eta_seconds: int
    ride_duration_seconds: int
    elapsed_seconds: int
    hour_of_day: int
    passenger_count: int | None
    cabin: CabinState  # mirrors vehicle API state
```

---

### `agent/llm.py` — Claude Agent

Claude tool definitions to implement:

```python
tools = [
    set_lights(brightness: int, color_temp: str),
    set_climate(temp_f: int, fan_speed: str),
    set_audio(action: str, genre: str | None),
    get_ride_info() -> RideContext,
    send_display(layout: str, data: dict),
]
```

**System prompt requirements:**
- Calm, brief co-pilot tone — 2 sentences max unless asked for more
- Inject full `RideContext` on every turn as a JSON block in the system prompt
- Include a list of proactive offers already made this ride so they are never repeated
- Never ask follow-up questions unless strictly necessary
- When taking an action, confirm briefly in speech and push a status card to the display

---

### `agent/audio_input.py` — VAD + STT

- Continuous microphone capture via `sounddevice` (cross-platform)
- `silero-vad` detects speech boundaries
- On speech end: buffer → `faster-whisper` → return transcript string
- Non-blocking: runs as an async generator yielding transcripts

---

### `agent/audio_output.py` — TTS

- Primary: ElevenLabs streaming API
- Fallback: `pyttsx3` (set via `config.py` flag)
- Playback must not block the VAD listening loop — run in a separate task
- Expose `speak(text: str)` coroutine

---

### `agent/proactive.py` — Trigger System

Async loop evaluating `RideContext` every 30 seconds. Each trigger fires at most once per ride session.

| Trigger | Condition | Offer |
|---|---|---|
| Boarding | `elapsed < 15s` | Welcome + one capability offer |
| Long ride | `duration > 600s AND elapsed < 120s` | Offer ambient lighting or music |
| Pre-arrival | `eta_seconds < 180` | Heads up, stop name |
| Nighttime | `hour > 20 OR hour < 6` | Offer to adjust cabin lighting |
| Mid-ride silence | `elapsed > 300s`, no recent interaction | Single gentle offer |

Triggers inject their message directly into the LLM turn as a `[PROACTIVE]` prefixed user message so the agent responds naturally in its established tone.

---

### `display/index.html` — Display UI

1080×360 fullscreen. Receives JSON over WebSocket from Python backend.

**Layouts:**

| Layout key | Content |
|---|---|
| `idle` | Route progress bar, ETA, next stop name |
| `speaking` | Live transcript of agent speech (accessibility) |
| `status` | Action confirmation card (e.g. "Lights: Dimmed · 72°F") |
| `arrival` | Large stop name, estimated walk time if available |

Display is output-only — no touch or click interaction.

---

### `agent/main.py` — Entrypoint

Async orchestration:

1. Start mock vehicle API server (subprocess or inline)
2. Start WebSocket server for display
3. Start VAD/STT loop as async generator
4. Start proactive trigger loop
5. On each transcript: send to LLM → execute tool calls → speak response

---

## Build Order

Build and validate in this sequence — each step should be independently testable before moving on:

1. **Mock vehicle API** — confirm state reads/writes via curl
2. **Display WebSocket server + HTML UI** — confirm layout switching works
3. **VAD + Whisper audio loop** — confirm transcripts printing to console
4. **Claude integration + tool use** — confirm tool calls execute against mock API
5. **TTS output** — confirm speech plays without blocking mic
6. **Proactive trigger system** — test with simulated ride contexts
7. **Wire `main.py`** — full end-to-end loop
8. **System prompt tuning** — run real scenario scripts, refine tone and brevity

---

## Mac → Linux Port Notes

- Abstract mic device names into `config.py` — different on macOS vs ALSA
- `sounddevice` handles cross-platform mic input
- Electron → Chromium `--kiosk` mode on Linux for display
- ElevenLabs → Kokoro TTS for fully offline Linux deploy
- Document any macOS-specific pip dependencies in `README.md`

---

## Tone & Personality Reference

> "I can adjust the lighting if you'd like — just let me know."
> "Heads up, you're arriving at Civic Center in about 3 minutes."
> "Playing some ambient music. Say 'stop' anytime."

- Never chipper, never robotic
- Offers options, doesn't push
- Confirms actions in one short sentence
- Goes quiet after offering — doesn't fill silence
