# Intent Detection Pipeline — `agent/audio_input.py` + `agent/intent.py`

## Overview

Replaces the wake word layer with continuous intent classification.
Clyde listens to all speech but only acts on utterances that are
actionable within the cabin context. No trigger phrase required —
riders speak naturally and Clyde responds when relevant.

---

## Pipeline Architecture

```
mic (continuous)
  → VAD (silero-vad)
    → [if echo_guard.is_gated()] discard
    → [if echo_guard.is_interrupt_window()] buffer for interrupt
    → Whisper STT (short utterance mode)
      → intent classifier (fast, low-token)
        → DIRECT_REQUEST   → full LLM turn
        → AMBIENT_INTENT   → soft action + confirm
        → CONVERSATIONAL   → discard silently
```

---

## Intent Classes

| Class | Description | Clyde behavior |
|---|---|---|
| `DIRECT_REQUEST` | Clearly asking Clyde to do something | Full LLM turn, execute |
| `AMBIENT_INTENT` | Implies a need the cabin can address | Conservative action + brief confirm |
| `CONVERSATIONAL` | Passenger talking to another passenger | Discard silently |

---

## Dependencies

```bash
pip install faster-whisper sounddevice torch torchaudio numpy anthropic
```

Add to `requirements.txt`:
```
faster-whisper>=1.0.0
sounddevice
torch
torchaudio
numpy
anthropic>=0.28.0
```

---

## `agent/intent.py`

```python
# agent/intent.py
# Classifies transcripts before passing to the full LLM.
# Fast, low-token call — uses claude-haiku for speed and cost.

import os
import logging
from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Intent class constants
DIRECT_REQUEST   = "DIRECT_REQUEST"
AMBIENT_INTENT   = "AMBIENT_INTENT"
CONVERSATIONAL   = "CONVERSATIONAL"

# Confidence threshold for ambient intents
# Below this, ambient intents are discarded rather than acted on
AMBIENT_CONFIDENCE_THRESHOLD = 0.75

CLASSIFY_PROMPT = """\
You are classifying speech from passengers inside an autonomous transit vehicle.
The vehicle assistant can control: lights, temperature, music/audio, and answer
questions about the route, ETA, stops, weather, flight status, sports scores,
news, and nearby places.

Classify the utterance as exactly one of:

DIRECT_REQUEST   — passenger is clearly asking the vehicle assistant to do
                   something or answer a question
AMBIENT_INTENT   — passenger is not directly addressing the assistant but their
                   words imply a need the vehicle could address
CONVERSATIONAL   — passenger is talking to another passenger with no relevance
                   to vehicle capabilities

Rules:
- When in doubt, classify as CONVERSATIONAL
- Transit vocabulary (ride, stop, arrive, get there) is common in passenger
  conversation — do not classify as DIRECT_REQUEST unless clearly a question
  or command directed at a system
- Short exclamations, reactions, and social phrases are always CONVERSATIONAL

Examples:
"turn down the lights a bit"          → DIRECT_REQUEST
"what time do we get there"           → DIRECT_REQUEST
"play some jazz"                       → DIRECT_REQUEST
"how's the weather at our stop"       → DIRECT_REQUEST
"did the Braves win last night"        → DIRECT_REQUEST
"it's really warm in here"            → AMBIENT_INTENT
"kind of loud"                         → AMBIENT_INTENT
"I wonder when we arrive"             → AMBIENT_INTENT
"little dark"                          → AMBIENT_INTENT
"did you see that game last night"    → CONVERSATIONAL
"I can't believe she said that"       → CONVERSATIONAL
"this is taking forever"              → CONVERSATIONAL
"nice view"                            → CONVERSATIONAL
"yeah totally"                         → CONVERSATIONAL

Utterance: "{transcript}"

Reply with only the class label and a confidence score 0.0-1.0 in this exact format:
CLASS|CONFIDENCE
Example: AMBIENT_INTENT|0.82
"""


async def classify(transcript: str) -> tuple[str, float]:
    """
    Returns (intent_class, confidence).
    Fast path — uses haiku model, max 20 tokens.
    """
    if not transcript or len(transcript.strip()) < 3:
        return CONVERSATIONAL, 1.0

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            messages=[{
                "role": "user",
                "content": CLASSIFY_PROMPT.format(transcript=transcript.strip())
            }]
        )

        raw = response.content[0].text.strip()
        parts = raw.split("|")

        if len(parts) != 2:
            logger.warning(f"Intent: unexpected format '{raw}' — defaulting to CONVERSATIONAL")
            return CONVERSATIONAL, 1.0

        intent = parts[0].strip()
        confidence = float(parts[1].strip())

        if intent not in (DIRECT_REQUEST, AMBIENT_INTENT, CONVERSATIONAL):
            logger.warning(f"Intent: unknown class '{intent}' — defaulting to CONVERSATIONAL")
            return CONVERSATIONAL, 1.0

        # Apply confidence gate for ambient intents
        if intent == AMBIENT_INTENT and confidence < AMBIENT_CONFIDENCE_THRESHOLD:
            logger.debug(f"Intent: AMBIENT_INTENT below threshold ({confidence}) — discarding")
            return CONVERSATIONAL, confidence

        logger.debug(f"Intent: '{transcript}' → {intent} ({confidence})")
        return intent, confidence

    except Exception as e:
        logger.error(f"Intent classifier error: {e}")
        return CONVERSATIONAL, 1.0  # fail safe — never act on classifier failure


def ambient_to_action(transcript: str) -> dict | None:
    """
    Maps common ambient intent phrases to conservative cabin actions.
    Used for fast ambient responses without a full LLM turn.

    Returns a tool call dict or None if no confident mapping exists.
    """
    t = transcript.lower().strip()

    # Temperature
    if any(w in t for w in ["warm", "hot", "stuffy"]):
        return {"tool": "set_climate", "args": {"temp_f": -2, "relative": True},
                "confirm": "Cooling it down a bit."}
    if any(w in t for w in ["cold", "chilly", "freezing"]):
        return {"tool": "set_climate", "args": {"temp_f": 2, "relative": True},
                "confirm": "Warming it up slightly."}

    # Lighting
    if any(w in t for w in ["dark", "dim", "can't see"]):
        return {"tool": "set_lights", "args": {"brightness": 20, "relative": True},
                "confirm": "Brightening the lights a bit."}
    if any(w in t for w in ["bright", "glare", "harsh"]):
        return {"tool": "set_lights", "args": {"brightness": -20, "relative": True},
                "confirm": "Dimming the lights slightly."}

    # Audio
    if any(w in t for w in ["loud", "too much noise"]):
        return {"tool": "set_audio", "args": {"action": "volume_down"},
                "confirm": "Turning it down."}
    if any(w in t for w in ["quiet", "silent", "mute"]):
        return {"tool": "set_audio", "args": {"action": "pause"},
                "confirm": "Music off."}

    # Route — ambient route queries go to full LLM, not fast path
    if any(w in t for w in ["wonder when", "long until", "almost there"]):
        return {"tool": "get_ride_info", "args": {},
                "confirm": None}  # LLM will formulate spoken response

    return None
```

---

## `agent/audio_input.py` (full updated implementation)

```python
# agent/audio_input.py
# Continuous mic capture with VAD, Whisper STT, and intent classification.
# No wake word — intent detection determines whether to act.

import asyncio
import logging
import os
import numpy as np
import sounddevice as sd
import torch
from faster_whisper import WhisperModel
from agent import echo_guard
from agent.intent import classify, ambient_to_action, DIRECT_REQUEST, AMBIENT_INTENT

logger = logging.getLogger(__name__)

# --- Config ---

SAMPLE_RATE       = 16000
BLOCK_SIZE        = 512           # ~32ms per block at 16kHz
WHISPER_MODEL     = os.getenv("WHISPER_MODEL", "base.en")
VAD_THRESHOLD     = 0.5           # silero-vad confidence threshold
SPEECH_END_PAD_MS = 600           # ms of silence before speech considered ended
MIN_SPEECH_MS     = 400           # discard segments shorter than this
MAX_SPEECH_MS     = 15000         # cap — prevents runaway buffering

# --- Model init ---

_whisper: WhisperModel | None = None
_vad_model = None
_vad_utils = None


def _get_whisper() -> WhisperModel:
    global _whisper
    if _whisper is None:
        logger.info(f"Loading Whisper model: {WHISPER_MODEL}")
        _whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper


def _get_vad():
    global _vad_model, _vad_utils
    if _vad_model is None:
        logger.info("Loading silero-vad model")
        _vad_model, _vad_utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            onnx=False,
        )
    return _vad_model, _vad_utils


def _vad_is_speech(chunk: np.ndarray) -> bool:
    model, (get_speech_timestamps, _, _, _, _) = _get_vad()
    tensor = torch.FloatTensor(chunk)
    confidence = model(tensor, SAMPLE_RATE).item()
    return confidence >= VAD_THRESHOLD


async def _transcribe(audio: np.ndarray) -> tuple[str | None, float]:
    """
    Returns (transcript, avg_confidence).
    Confidence is used to gate low-quality transcriptions.
    """
    loop = asyncio.get_event_loop()

    def _run():
        model = _get_whisper()
        segments, info = model.transcribe(
            audio,
            language="en",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300}
        )
        segment_list = list(segments)
        if not segment_list:
            return None, 0.0

        text = " ".join(s.text for s in segment_list).strip()
        avg_logprob = sum(s.avg_logprob for s in segment_list) / len(segment_list)
        # Convert log probability to 0-1 confidence approximation
        confidence = min(1.0, max(0.0, 1.0 + avg_logprob / 5.0))
        return text, confidence

    return await loop.run_in_executor(None, _run)


# --- Interrupt buffer ---
# Audio buffered during echo_guard interrupt window
_interrupt_buffer: list[np.ndarray] = []


async def _flush_interrupt_buffer(
    transcript_queue: asyncio.Queue,
    interrupt_confirm_fn
) -> None:
    """
    Called when TTS is cancelled due to an interrupt.
    Transcribes buffered audio and queues if valid.
    """
    if not _interrupt_buffer:
        return

    audio = np.concatenate(_interrupt_buffer)
    _interrupt_buffer.clear()

    duration_ms = len(audio) / SAMPLE_RATE * 1000
    if duration_ms < MIN_SPEECH_MS:
        return

    transcript, confidence = await _transcribe(audio)
    if not transcript:
        return

    if echo_guard.is_echo(transcript):
        logger.debug(f"AudioInput: interrupt buffer echo discarded: '{transcript}'")
        return

    logger.info(f"AudioInput: interrupt transcript: '{transcript}' (conf: {confidence:.2f})")

    # Brief acknowledgment before processing
    if interrupt_confirm_fn:
        await interrupt_confirm_fn()

    await transcript_queue.put((transcript, confidence))


# --- Main transcript stream ---

async def transcript_stream(
    on_interrupt=None
):
    """
    Async generator yielding (transcript, intent, confidence) tuples.

    on_interrupt: optional async callable — called when a human interrupt
                  is detected during TTS playback. Use to cancel speech.

    Yields:
        tuple[str, str, float] — (transcript, intent_class, confidence)
    """
    transcript_queue: asyncio.Queue = asyncio.Queue()

    # State
    speech_buffer: list[np.ndarray] = []
    speech_active: bool = False
    silence_frames: int = 0
    silence_frames_threshold = int((SPEECH_END_PAD_MS / 1000) * (SAMPLE_RATE / BLOCK_SIZE))

    def audio_callback(indata, frames, time_info, status):
        nonlocal speech_active, silence_frames

        chunk = indata[:, 0].copy()

        # Hard gate — discard entirely
        if echo_guard.is_gated():
            return

        # Interrupt window — buffer only, VAD check for human voice
        if echo_guard.is_interrupt_window():
            if _vad_is_speech(chunk):
                _interrupt_buffer.append(chunk)
                # Signal interrupt — cancel TTS
                if on_interrupt:
                    asyncio.get_event_loop().call_soon_threadsafe(
                        lambda: asyncio.create_task(_handle_interrupt(
                            transcript_queue, on_interrupt
                        ))
                    )
            return

        # Normal listening path
        is_speech = _vad_is_speech(chunk)

        if is_speech:
            speech_active = True
            silence_frames = 0
            speech_buffer.append(chunk)

            # Cap buffer to prevent runaway
            buffer_ms = len(speech_buffer) * BLOCK_SIZE / SAMPLE_RATE * 1000
            if buffer_ms > MAX_SPEECH_MS:
                asyncio.get_event_loop().call_soon_threadsafe(
                    transcript_queue.put_nowait,
                    np.concatenate(speech_buffer)
                )
                speech_buffer.clear()
                speech_active = False

        elif speech_active:
            silence_frames += 1
            speech_buffer.append(chunk)  # include trailing silence for natural end

            if silence_frames >= silence_frames_threshold:
                audio = np.concatenate(speech_buffer)
                speech_buffer.clear()
                speech_active = False
                silence_frames = 0

                duration_ms = len(audio) / SAMPLE_RATE * 1000
                if duration_ms >= MIN_SPEECH_MS:
                    asyncio.get_event_loop().call_soon_threadsafe(
                        transcript_queue.put_nowait, audio
                    )

    async def _handle_interrupt(queue, interrupt_fn):
        await interrupt_fn()
        await _flush_interrupt_buffer(queue, None)

    # Start mic stream
    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        blocksize=BLOCK_SIZE,
        dtype="float32",
        channels=1,
        callback=audio_callback,
    ):
        logger.info("AudioInput: listening")

        while True:
            audio = await transcript_queue.get()
            if not isinstance(audio, np.ndarray):
                continue

            transcript, whisper_confidence = await _transcribe(audio)

            if not transcript:
                continue

            # Discard low-confidence transcriptions
            if whisper_confidence < 0.3:
                logger.debug(f"AudioInput: low confidence transcript discarded ({whisper_confidence:.2f})")
                continue

            # Echo guard — last line of defense
            if echo_guard.is_echo(transcript):
                logger.debug(f"AudioInput: echo discarded: '{transcript}'")
                continue

            logger.info(f"AudioInput: '{transcript}' (conf: {whisper_confidence:.2f})")

            # Intent classification
            intent, intent_confidence = await classify(transcript)

            if intent == "CONVERSATIONAL":
                logger.debug(f"AudioInput: conversational — discarded")
                continue

            yield transcript, intent, intent_confidence
```

---

## `agent/main.py` — Updated Processing Loop

```python
from agent.audio_input import transcript_stream
from agent.intent import DIRECT_REQUEST, AMBIENT_INTENT, ambient_to_action
from agent.audio_output import say, cancel_speech

async def run_agent(ride_context, ws_broadcast):

    async def on_interrupt():
        """Called when a human interrupt is detected during TTS."""
        await cancel_speech()

    async for transcript, intent, confidence in transcript_stream(
        on_interrupt=on_interrupt
    ):
        if intent == DIRECT_REQUEST:
            # Full LLM turn
            await ws_broadcast({"type": "state", "value": "processing"})
            response = await llm.process(transcript, ride_context)
            await say(response, ws_broadcast=ws_broadcast)

        elif intent == AMBIENT_INTENT:
            # Try fast-path action mapping first
            action = ambient_to_action(transcript)

            if action and action["tool"] != "get_ride_info":
                # Execute directly — no LLM turn needed
                await vehicle_api.call(action["tool"], action["args"])
                if action["confirm"]:
                    await say(action["confirm"], ws_broadcast=ws_broadcast)
            else:
                # Ambient intent needs LLM context (e.g. route queries)
                await ws_broadcast({"type": "state", "value": "processing"})
                response = await llm.process(transcript, ride_context)
                await say(response, ws_broadcast=ws_broadcast)
```

---

## Recency Gate — prevent repeated ambient triggers

Add to `agent/intent.py` to avoid acting repeatedly on a single offhand comment:

```python
import time

_last_ambient_action: dict[str, float] = {}  # tool → timestamp
AMBIENT_RECENCY_GATE_SECONDS = 60


def ambient_is_recent(tool: str) -> bool:
    """Returns True if this ambient action was taken in the last 60 seconds."""
    last = _last_ambient_action.get(tool, 0)
    return (time.monotonic() - last) < AMBIENT_RECENCY_GATE_SECONDS


def record_ambient_action(tool: str) -> None:
    _last_ambient_action[tool] = time.monotonic()


def clear_ambient_history() -> None:
    _last_ambient_action.clear()
```

Update `ambient_to_action` call site in `main.py`:

```python
elif intent == AMBIENT_INTENT:
    action = ambient_to_action(transcript)

    if action and not intent.ambient_is_recent(action["tool"]):
        await vehicle_api.call(action["tool"], action["args"])
        intent.record_ambient_action(action["tool"])
        if action["confirm"]:
            await say(action["confirm"], ws_broadcast=ws_broadcast)
```

---

## System Prompt Addition — `agent/llm.py`

Add to the Claude system prompt so the LLM understands the interaction model:

```
Riders do not need to address you directly. You receive utterances that have
already been classified as either a direct request or an ambient intent by an
upstream classifier. Treat every transcript you receive as genuinely directed
at you — do not ask the rider to clarify whether they meant to address you.

For ambient intents, act conservatively and confirm briefly. Do not ask
follow-up questions unless the request is genuinely ambiguous about what
action to take.
```

---

## Tuning Guide

| Parameter | Default | Tune when... |
|---|---|---|
| `VAD_THRESHOLD` | 0.5 | Too many false triggers / missing real speech |
| `SPEECH_END_PAD_MS` | 600ms | Clyde cuts off natural speech pauses |
| `MIN_SPEECH_MS` | 400ms | Short commands being dropped |
| `AMBIENT_CONFIDENCE_THRESHOLD` | 0.75 | Too many ambient false positives |
| `AMBIENT_RECENCY_GATE_SECONDS` | 60s | Same ambient action triggering repeatedly |
| Whisper confidence gate | 0.3 | Garbled multi-speaker audio acting on bad transcripts |

---

## UXR Testing Scenarios

Prepare these for your first cabin session to validate the classifier:

**Should trigger DIRECT_REQUEST:**
- "What time do we get there?"
- "Can you play something calming?"
- "Turn the lights down"
- "What's the weather like at our stop?"

**Should trigger AMBIENT_INTENT:**
- "It's a little warm in here"
- "Kind of dark"
- "I wonder how long this takes"
- "Could use some music"

**Should be CONVERSATIONAL (discarded):**
- "Did you hear about that?"
- "This is taking forever"
- "I love this part of the city"
- "Yeah, totally agree"
- Laughter, reactions, back-channel phrases

Run each category 3–5 times with different speakers and log the classifier
output. Adjust `AMBIENT_CONFIDENCE_THRESHOLD` if ambient intents are either
over-triggering or being missed.

---

## File Placement

```
transit-agent/
└── agent/
    ├── audio_input.py    ← full replacement
    └── intent.py         ← new
```
