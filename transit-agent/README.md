# Transit Cabin Agent

Voice-first LLM agent for in-cabin control of a small autonomous public transit vehicle. Input is microphone only; output is speech (TTS), a 1080×360 display, and mock vehicle API (lights, climate, audio). The agent is proactive and uses ride context to offer help at key moments.

## Tech Stack

- **Python 3.11+** (asyncio throughout)
- **LLM**: Claude API (`claude-sonnet-4-20250514`) with tool use
- **STT**: faster-whisper (local)
- **VAD**: silero-vad (torch) or energy-based fallback
- **TTS**: ElevenLabs API (pyttsx3 offline fallback)
- **Display**: 1080×360 WebSocket-driven UI (open `display/index.html` in browser or Electron)
- **Mock vehicle API**: FastAPI on `localhost:8001`

## Setup

```bash
cd transit-agent
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY; optionally ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID
```

## Build Order (validation)

1. **Mock vehicle API** — from repo root: `python -m vehicle_api.server` then `curl http://127.0.0.1:8001/state` and `curl -X POST http://127.0.0.1:8001/lights -H "Content-Type: application/json" -d '{"brightness":50,"color_temp":"warm"}'`
2. **Display** — open `display/index.html` in a browser (WS connects to `ws://localhost:8765`). Start the agent to run the WebSocket server, or run a minimal WS server to test layout switching.
3. **VAD + Whisper** — run agent; speak into mic; transcripts should log.
4. **Claude + tools** — ensure `ANTHROPIC_API_KEY` is set; say "turn down the lights" and confirm tool calls and API updates.
5. **TTS** — confirm agent speech plays (ElevenLabs or pyttsx3).
6. **Proactive triggers** — let the agent run; triggers fire at most once per session (boarding, long ride, pre-arrival, nighttime, mid-ride silence).
7. **Full loop** — `python -m agent.main` from `transit-agent` (or `PYTHONPATH=. python agent/main.py`).

## Run

From the `transit-agent` directory:

```bash
PYTHONPATH=. python -m agent.main
```

- Vehicle API starts on port 8001.
- Display WebSocket server on port 8765. Open `display/index.html` in a browser (or Electron in kiosk for 1080×360).
- Microphone is captured continuously; after speech end, transcript is sent to Claude; tool calls run against the mock API; response is spoken and display updated.

## Mac → Linux

- Mic device: set `AUDIO_INPUT_DEVICE` / `AUDIO_OUTPUT_DEVICE` in config or env (names differ on macOS vs ALSA).
- Display: use Chromium `--kiosk` on Linux instead of Electron if needed.
- TTS: for fully offline Linux, consider Kokoro TTS instead of ElevenLabs; toggle in `config.py`.

## Tone

Calm, brief, co-pilot. Two sentences max unless the user asks for more. Confirm actions in one short sentence and push a status card to the display. Never chipper or robotic; offer options, don’t push; go quiet after offering.
