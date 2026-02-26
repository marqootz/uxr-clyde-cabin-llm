"""FastAPI mock vehicle API — lights, climate, audio. All state in-memory."""

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from vehicle_api.state import CabinState, LightsState, ClimateState, AudioState

app = FastAPI(title="Mock Vehicle API")
state = CabinState()


# --- Request bodies ---

class LightsBody(BaseModel):
    brightness: int
    color_temp: str


class ClimateBody(BaseModel):
    temp_f: int
    fan_speed: str


class AudioBody(BaseModel):
    action: str
    genre: str | None = None


# --- Endpoints ---

@app.get("/state")
def get_state() -> dict:
    return state.to_dict()


@app.post("/lights")
def set_lights(body: LightsBody) -> dict:
    state.lights.brightness = body.brightness
    state.lights.color_temp = body.color_temp
    print(f"[Vehicle API] lights: brightness={body.brightness}, color_temp={body.color_temp}")
    return state.to_dict()


@app.post("/climate")
def set_climate(body: ClimateBody) -> dict:
    state.climate.temp_f = body.temp_f
    state.climate.fan_speed = body.fan_speed
    print(f"[Vehicle API] climate: temp_f={body.temp_f}, fan_speed={body.fan_speed}")
    return state.to_dict()


@app.post("/audio")
def set_audio(body: AudioBody) -> dict:
    state.audio.action = body.action
    state.audio.genre = body.genre
    print(f"[Vehicle API] audio: action={body.action}, genre={body.genre}")
    return state.to_dict()


def run(port: int | None = None) -> None:
    import os
    port = port or int(os.environ.get("VEHICLE_API_PORT", "8001"))
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    run()
