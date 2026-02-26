# agent/echo_guard.py
# Manages the speaking gate, holdoff window, and transcript similarity check.
# All audio_input.py and main.py gating goes through this module.
# See ECHO_GUARD.md for usage.

import time
from difflib import SequenceMatcher

# --- Config ---

HOLDOFF_SECONDS = 0.45  # silence window kept after TTS ends (tune per cabin)
ECHO_THRESHOLD = 0.70  # similarity ratio above which a transcript is discarded
RECENT_SPEECH_WINDOW = 5  # number of recent utterances to check against

# --- State ---

_is_speaking: bool = False
_holdoff_until: float = 0.0
_recent_utterances: list[str] = []  # rolling window of recent agent speech


# --- Gate API ---

def set_speaking(active: bool, holdoff: bool = True) -> None:
    """
    Called by audio_output when TTS starts and ends.
    When ending (active=False), starts the holdoff timer.
    """
    global _is_speaking, _holdoff_until
    _is_speaking = active
    if not active and holdoff:
        _holdoff_until = time.monotonic() + HOLDOFF_SECONDS


def is_gated() -> bool:
    """
    Returns True if audio input should be discarded.
    Covers both active TTS and the post-speech holdoff window.
    """
    if _is_speaking:
        return True
    if time.monotonic() < _holdoff_until:
        return True
    return False


# --- Transcript similarity check ---

def register_utterance(text: str) -> None:
    """
    Call this every time Clyde speaks. Stores the utterance
    for echo detection on incoming transcripts.
    """
    global _recent_utterances
    _recent_utterances.append(text.lower().strip())
    if len(_recent_utterances) > RECENT_SPEECH_WINDOW:
        _recent_utterances.pop(0)


def is_echo(transcript: str) -> bool:
    """
    Returns True if the transcript closely matches any recent agent utterance.
    Use this as a last line of defense after the gate check.
    """
    if not _recent_utterances or not transcript:
        return False

    t = transcript.lower().strip()

    for utterance in _recent_utterances:
        ratio = SequenceMatcher(None, t, utterance).ratio()
        if ratio >= ECHO_THRESHOLD:
            return True

        # Also check if transcript is a substring of a recent utterance
        # (catches partial captures at the start/end of TTS playback)
        if len(t) > 8 and t in utterance:
            return True

    return False


def clear() -> None:
    """Reset all state — call at the start of each new ride session."""
    global _is_speaking, _holdoff_until, _recent_utterances
    _is_speaking = False
    _holdoff_until = 0.0
    _recent_utterances = []
