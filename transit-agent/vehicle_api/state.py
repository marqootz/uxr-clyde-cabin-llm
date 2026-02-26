"""In-memory cabin state mirrored by the mock vehicle API."""

from dataclasses import dataclass, field


@dataclass
class LightsState:
    brightness: int = 100  # 0–100
    color_temp: str = "neutral"  # warm | neutral | cool


@dataclass
class ClimateState:
    temp_f: int = 72
    fan_speed: str = "auto"  # off | low | medium | high | auto


@dataclass
class AudioState:
    action: str = "idle"  # idle | playing | paused
    genre: str | None = None


@dataclass
class CabinState:
    lights: LightsState = field(default_factory=LightsState)
    climate: ClimateState = field(default_factory=ClimateState)
    audio: AudioState = field(default_factory=AudioState)

    @classmethod
    def from_dict(cls, d: dict) -> "CabinState":
        """Build CabinState from vehicle API GET /state response (top-level keys: lights, climate, audio)."""
        lights = d.get("lights", {})
        climate = d.get("climate", {})
        audio = d.get("audio", {})
        return cls(
            lights=LightsState(
                brightness=lights.get("brightness", 100),
                color_temp=lights.get("color_temp", "neutral"),
            ),
            climate=ClimateState(
                temp_f=climate.get("temp_f", 72),
                fan_speed=climate.get("fan_speed", "auto"),
            ),
            audio=AudioState(
                action=audio.get("action", "idle"),
                genre=audio.get("genre"),
            ),
        )

    def to_dict(self) -> dict:
        return {
            "lights": {
                "brightness": self.lights.brightness,
                "color_temp": self.lights.color_temp,
            },
            "climate": {
                "temp_f": self.climate.temp_f,
                "fan_speed": self.climate.fan_speed,
            },
            "audio": {
                "action": self.audio.action,
                "genre": self.audio.genre,
            },
        }
