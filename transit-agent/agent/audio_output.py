"""TTS playback. ElevenLabs primary; pyttsx3 fallback. Non-blocking via separate task."""

from __future__ import annotations

import asyncio
import logging
import math
import random
import shutil
from pathlib import Path

import config
from agent import echo_guard
from agent import display_server

logger = logging.getLogger(__name__)

# Send at ~60/sec so display scale isn't limited to ~30 updates/sec (was 0.033).
_AUDIO_LEVEL_INTERVAL = 0.016


# Jitter refreshed at 1/4 the main rate (~15 Hz).
_JITTER_INTERVAL = _AUDIO_LEVEL_INTERVAL * 6


async def _emit_audio_level_envelope(stop_event: asyncio.Event) -> None:
    """Send an irregular envelope (ramp then varying sustain). Higher rate + punchier curve reduce lethargic feel."""
    t = 0.0
    jitter = 0.0
    next_jitter_t = 0.0
    while not stop_event.is_set():
        if t < 0.5:
            level = 0.3 + 0.4 * (t / 0.5)
        else:
            if t >= next_jitter_t:
                jitter = 0.10 * (2 * random.random() - 1)
                next_jitter_t = t + _JITTER_INTERVAL
            level = 0.6 + 0.06 * math.sin(t * 2.3) + 0.05 * math.sin(t * 4.7) + 0.04 * math.sin(t * 6.1)
            level += 0.03 * math.sin(t * 0.97) + 0.07 * math.sin(t * 9.2)
            level += jitter
        level = max(0.0, min(1.0, level))
        await display_server.broadcast_audio_level(level)
        await asyncio.sleep(_AUDIO_LEVEL_INTERVAL)
        t += _AUDIO_LEVEL_INTERVAL


_speak_queue: asyncio.Queue[tuple[str, asyncio.Future[None]]] | None = None


def _normalize_for_tts(text: str) -> str:
    """Strip trailing punctuation so TTS doesn't pause or speak it; collapse repeated punctuation."""
    if not text or not text.strip():
        return text
    t = text.strip()
    while t and t[-1] in ".,!?;:":
        t = t[:-1].rstrip()
    return t if t else text.strip()


def _duration_ms_from_alignment(alignment: dict | None) -> int | None:
    """Extract speech duration in ms from ElevenLabs alignment (character_end_times_seconds)."""
    if not alignment:
        return None
    ends = alignment.get("character_end_times_seconds") or alignment.get("character_end_times")
    if not ends:
        return None
    try:
        return int(ends[-1] * 1000)
    except (IndexError, TypeError, ValueError):
        return None


async def _fetch_elevenlabs_with_timestamps(text: str) -> tuple[bytes, int | None]:
    """Fetch TTS from ElevenLabs with-timestamps endpoint. Returns (audio_bytes, duration_ms or None)."""
    if not config.ELEVENLABS_API_KEY or not config.ELEVENLABS_VOICE_ID:
        raise RuntimeError("ElevenLabs API key or voice ID not set")
    import base64
    import httpx
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}/with-timestamps"
    headers = {
        "xi-api-key": config.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "apply_text_normalization": "auto",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    audio_b64 = data.get("audio_base64")
    if not audio_b64:
        raise RuntimeError("ElevenLabs with-timestamps returned no audio_base64")
    audio_bytes = base64.b64decode(audio_b64)
    alignment = data.get("alignment") or data.get("normalized_alignment")
    duration_ms = _duration_ms_from_alignment(alignment)
    return (audio_bytes, duration_ms)


async def _fetch_elevenlabs_fallback(text: str) -> tuple[bytes, int | None]:
    """Fallback: regular TTS endpoint when with-timestamps fails. Returns (audio_bytes, None)."""
    if not config.ELEVENLABS_API_KEY or not config.ELEVENLABS_VOICE_ID:
        raise RuntimeError("ElevenLabs API key or voice ID not set")
    import httpx
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": config.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json={"text": text, "model_id": "eleven_monolingual_v1"}, headers=headers)
        r.raise_for_status()
        return (r.content, None)


async def _play_audio_bytes(audio_bytes: bytes) -> None:
    """Play audio bytes (mp3). Uses pygame or afplay fallback."""
    try:
        import pygame
        pygame.mixer.init(frequency=22050, size=-16, channels=1)
        snd = pygame.mixer.Sound(buffer=audio_bytes)
        snd.play()
        while pygame.mixer.get_busy():
            await asyncio.sleep(0.1)
    except ImportError:
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            path = f.name
        try:
            proc = await asyncio.create_subprocess_exec(
                "afplay", path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass


def _play_pyttsx3(text: str) -> None:
    """Synchronous pyttsx3 playback (run in executor)."""
    import pyttsx3
    engine = pyttsx3.init()
    engine.say(text)
    engine.runAndWait()


async def play_local_file(file_path: str | Path) -> None:
    """Play a local audio file (e.g. .mp3) and return when done. Uses afplay on macOS, else ffplay."""
    path = Path(file_path)
    if not path.is_file():
        logger.warning("play_local_file: not a file %s", path)
        return
    try:
        if shutil.which("afplay"):
            proc = await asyncio.create_subprocess_exec(
                "afplay", str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        elif shutil.which("ffplay"):
            proc = await asyncio.create_subprocess_exec(
                "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        else:
            logger.warning("play_local_file: no afplay or ffplay found")
    except Exception as e:
        logger.warning("play_local_file failed: %s", e)


async def speak(text: str) -> None:
    """Speak the given text. Returns only after playback has finished (so callers can suppress mic feedback)."""
    if not text or not text.strip():
        return
    global _speak_queue
    if _speak_queue is None:
        _speak_queue = asyncio.Queue()
        asyncio.create_task(_speaker_loop())
    done: asyncio.Future[None] = asyncio.get_event_loop().create_future()
    await _speak_queue.put((text, done))
    await done


async def speak_nonblocking(text: str) -> None:
    """Queue speech and return immediately without waiting for playback completion."""
    if not text or not text.strip():
        return
    global _speak_queue
    if _speak_queue is None:
        _speak_queue = asyncio.Queue()
        asyncio.create_task(_speaker_loop())
    done: asyncio.Future[None] = asyncio.get_event_loop().create_future()
    await _speak_queue.put((text, done))


async def _speaker_loop() -> None:
    """Dedicated loop that consumes the speak queue and plays TTS; completes future when done."""
    global _speak_queue
    loop = asyncio.get_event_loop()
    while _speak_queue is not None:
        try:
            item = await asyncio.wait_for(_speak_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        text, done = item
        text = _normalize_for_tts(text)
        if not text:
            if not done.done():
                done.set_result(None)
            continue
        echo_guard.register_utterance(text)
        echo_guard.set_speaking(True)
        stop_level_event = asyncio.Event()
        level_task = asyncio.create_task(_emit_audio_level_envelope(stop_level_event))
        turn_t0 = asyncio.get_event_loop().time()
        try:
            if config.USE_ELEVENLABS:
                try:
                    t0 = asyncio.get_event_loop().time()
                    audio_bytes, duration_ms = await _fetch_elevenlabs_with_timestamps(text)
                    logger.info("Latency TTS fetch_with_timestamps_ms=%d text_len=%d", int((asyncio.get_event_loop().time() - t0) * 1000), len(text))
                except Exception:
                    t0 = asyncio.get_event_loop().time()
                    audio_bytes, duration_ms = await _fetch_elevenlabs_fallback(text)
                    logger.info("Latency TTS fetch_fallback_ms=%d text_len=%d", int((asyncio.get_event_loop().time() - t0) * 1000), len(text))
                data: dict[str, object] = {"text": text}
                if duration_ms is not None:
                    data["duration_ms"] = duration_ms
                await display_server.send_layout("speaking", data)
                t0 = asyncio.get_event_loop().time()
                await _play_audio_bytes(audio_bytes)
                logger.info("Latency TTS playback_ms=%d text_len=%d", int((asyncio.get_event_loop().time() - t0) * 1000), len(text))
            else:
                await display_server.send_layout("speaking", {"text": text})
                t0 = asyncio.get_event_loop().time()
                await loop.run_in_executor(None, _play_pyttsx3, text)
                logger.info("Latency TTS pyttsx3_playback_ms=%d text_len=%d", int((asyncio.get_event_loop().time() - t0) * 1000), len(text))
        except Exception as e:
            logger.exception("TTS playback failed: %s", e)
        finally:
            logger.info("Latency TTS total_turn_ms=%d text_len=%d", int((asyncio.get_event_loop().time() - turn_t0) * 1000), len(text))
            stop_level_event.set()
            try:
                await asyncio.wait_for(level_task, timeout=0.5)
            except asyncio.TimeoutError:
                level_task.cancel()
            echo_guard.set_speaking(False, holdoff=True)
            if not done.done():
                done.set_result(None)
