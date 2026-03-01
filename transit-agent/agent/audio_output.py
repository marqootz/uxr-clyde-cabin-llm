"""TTS playback. ElevenLabs primary; pyttsx3 fallback. Non-blocking via separate task."""

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


async def _play_elevenlabs(text: str) -> None:
    """Stream TTS from ElevenLabs and play (blocking in executor or async)."""
    if not config.ELEVENLABS_API_KEY or not config.ELEVENLABS_VOICE_ID:
        raise RuntimeError("ElevenLabs API key or voice ID not set")
    try:
        import httpx
        url = "https://api.elevenlabs.io/v1/text-to-speech/" + config.ELEVENLABS_VOICE_ID
        headers = {
            "xi-api-key": config.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json={"text": text, "model_id": "eleven_monolingual_v1"}, headers=headers)
            r.raise_for_status()
            audio_bytes = r.content
        # Play with a simple player (e.g. pygame or subprocess aplay/mpg123)
        try:
            import pygame
            pygame.mixer.init(frequency=22050, size=-16, channels=1)
            import io
            snd = pygame.mixer.Sound(buffer=audio_bytes)
            snd.play()
            while pygame.mixer.get_busy():
                await asyncio.sleep(0.1)
        except ImportError:
            # Fallback: write to temp file and play with afplay (macOS) or aplay
            import tempfile
            import subprocess
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
                import os
                try:
                    os.unlink(path)
                except Exception:
                    pass
    except Exception as e:
        logger.exception("ElevenLabs TTS failed: %s", e)
        raise


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
        try:
            if config.USE_ELEVENLABS:
                await _play_elevenlabs(text)
            else:
                await loop.run_in_executor(None, _play_pyttsx3, text)
        except Exception as e:
            logger.exception("TTS playback failed: %s", e)
        finally:
            stop_level_event.set()
            try:
                await asyncio.wait_for(level_task, timeout=0.5)
            except asyncio.TimeoutError:
                level_task.cancel()
            echo_guard.set_speaking(False, holdoff=True)
            if not done.done():
                done.set_result(None)
