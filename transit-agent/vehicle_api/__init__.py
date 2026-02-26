"""Mock vehicle API for cabin control (lights, climate, audio)."""

from vehicle_api.state import CabinState, LightsState, ClimateState, AudioState
from vehicle_api.server import app

__all__ = ["CabinState", "LightsState", "ClimateState", "AudioState", "app"]
