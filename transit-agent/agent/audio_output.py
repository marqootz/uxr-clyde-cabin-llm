"""TTS playback. ElevenLabs primary; pyttsx3 fallback. Non-blocking via separate task."""

import asyncio
import logging

import config
from agent import echo_guard

logger = logging.getLogger(__name__)

_speak_queue: asyncio.Queue[tuple[str, asyncio.Future[None]]] | None = None


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
        echo_guard.register_utterance(text)
        echo_guard.set_speaking(True)
        try:
            if config.USE_ELEVENLABS:
                await _play_elevenlabs(text)
            else:
                await loop.run_in_executor(None, _play_pyttsx3, text)
        except Exception as e:
            logger.exception("TTS playback failed: %s", e)
        finally:
            echo_guard.set_speaking(False, holdoff=True)
            if not done.done():
                done.set_result(None)
