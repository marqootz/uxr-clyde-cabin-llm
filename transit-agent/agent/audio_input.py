"""VAD + Whisper STT pipeline. Continuous mic capture, speech boundaries, async transcript stream. Gated by echo_guard."""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from agent import echo_guard

logger = logging.getLogger(__name__)

# Optional: silero-vad for speech detection (fallback: simple energy threshold)
try:
    import torch
    torch.set_num_threads(1)
    _vad_model, _utils = torch.hub.load(repo_or_dir="snakers4/silero-vad", model="silero_vad", trust_repo=True)
    _get_speech_timestamps = _utils[0]
    HAS_SILERO = True
except Exception as e:
    logger.warning("Silero VAD not available: %s. Using energy-based VAD.", e)
    HAS_SILERO = False

_executor = ThreadPoolExecutor(max_workers=1)

# Audio config
SAMPLE_RATE = 16000
CHUNK_MS = 30
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_MS / 1000)
SILENCE_MS = 700  # end of utterance after this much silence
MIN_UTTERANCE_MS = 400


def _energy_vad(samples: np.ndarray, threshold: float = 0.01) -> bool:
    """Simple energy-based voice activity."""
    return float(np.abs(samples).mean()) > threshold


# Queue-based async generator: callback runs in sounddevice thread; Whisper runs in executor; results go to queue.
_transcript_queue: asyncio.Queue | None = None


async def transcripts_from_mic_queued(
    model_name: str = "base.en",
    device: str = "cpu",
    input_device: int | None = None,
):
    """Async generator yielding transcript strings. Uses a queue fed by the audio callback."""
    global _transcript_queue
    _transcript_queue = asyncio.Queue()
    model = WhisperModel(model_name, device=device, compute_type="int8")
    buffer: list[np.ndarray] = []
    silence_frames = 0
    speech_started = False
    loop = asyncio.get_event_loop()

    def audio_callback(indata: np.ndarray, frames: int, time_info, status):
        nonlocal speech_started, silence_frames
        if status:
            logger.debug("Sounddevice: %s", status)
        if echo_guard.is_gated():
            buffer.clear()
            speech_started = False
            silence_frames = 0
            return
        chunk = indata.copy().flatten()
        if HAS_SILERO:
            ts = _get_speech_timestamps(
                torch.from_numpy(chunk).float(),
                _vad_model,
                sampling_rate=SAMPLE_RATE,
                threshold=0.5,
                min_speech_duration_ms=100,
            )
            is_speech = bool(ts)
        else:
            is_speech = _energy_vad(chunk)

        if is_speech:
            speech_started = True
            silence_frames = 0
            buffer.append(chunk)
        elif speech_started:
            buffer.append(chunk)
            silence_frames += 1
            if silence_frames * CHUNK_MS >= SILENCE_MS:
                to_process = np.concatenate(buffer) if buffer else np.array([], dtype=np.float32)
                buffer.clear()
                speech_started = False
                silence_frames = 0
                if len(to_process) >= int(MIN_UTTERANCE_MS / 1000 * SAMPLE_RATE):
                    def run_whisper():
                        segments, _ = model.transcribe(to_process, language="en", vad_filter=True)
                        return " ".join(s.text.strip() for s in segments if s.text).strip()

                    def put_result(fut):
                        try:
                            text = fut.result()
                            if text and _transcript_queue is not None:
                                _transcript_queue.put_nowait((text, time.monotonic()))
                        except Exception as e:
                            logger.exception("Whisper failed: %s", e)

                    fut = loop.run_in_executor(_executor, run_whisper)
                    loop.call_soon_threadsafe(fut.add_done_callback, put_result)
        else:
            buffer.clear()

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=CHUNK_SAMPLES,
        device=input_device,
        callback=audio_callback,
    )
    stream.start()
    try:
        while True:
            try:
                item = await asyncio.wait_for(_transcript_queue.get(), timeout=0.5)
                text, ts = item
                if echo_guard.is_echo(text):
                    logger.debug("Skipping echo transcript: %r", text[:50])
                    continue
                yield (text, ts)
            except asyncio.TimeoutError:
                continue
    finally:
        stream.stop()
        stream.close()
        _transcript_queue = None


# Public API: use queued version. Yields (text, timestamp_monotonic) for feedback suppression.
async def transcript_generator(
    model_name: str = "base.en",
    device: str = "cpu",
    input_device: int | None = None,
):
    """Async generator yielding (transcript_text, timestamp) from the microphone."""
    async for item in transcripts_from_mic_queued(model_name, device, input_device):
        yield item
